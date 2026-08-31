import Foundation
import Observation
import ZaolangKit

/// 任务详情：SSE 实时更新 + 5 秒轮询兜底同时跑（`roadmap.md` 第 5 条契约缺口的简化实现——
/// `EventStreamClient` 内部退避重连是无限重试，没有"连续三次失败降级轮询"的计数器；
/// 与其在这里精确复刻那套状态机，直接并行跑一个轮询循环更简单也更可靠：
/// SSE 到就提前更新，轮询兜底保证最多 5 秒内一定和服务端状态对齐）。
@MainActor
@Observable
final class JobDetailViewModel {
    private let apiClient: APIClient
    private let eventStreamClient: EventStreamClient
    let jobID: String

    private(set) var state: LoadableState<GenerationJobResponse> = .loading
    private(set) var isCancelling = false
    private(set) var isRetrying = false
    private(set) var actionError: String?
    /// 重试成功后落一个新 job id，调用方（`JobDetailView`）据此把当前屏幕换到新任务，
    /// 绝不能停在旧任务详情上继续轮询一个已经不会再变化的终态。
    private(set) var retriedJobID: String?

    private(set) var liveThinking = ""

    private(set) var inputRequest: JobInputRequestResponse?
    private(set) var isLoadingInputRequest = false
    private(set) var inputRequestError: String?
    private(set) var isSubmittingAnswer = false
    private(set) var answerSubmitted = false

    private var pollingTask: Task<Void, Never>?
    private var sseTask: Task<Void, Never>?
    private var inputRequestTask: Task<Void, Never>?
    private var lastAppliedSequence = -1
    private var liveThinkingNodeId: String?

    init(jobID: String, apiClient: APIClient, eventStreamClient: EventStreamClient) {
        self.jobID = jobID
        self.apiClient = apiClient
        self.eventStreamClient = eventStreamClient
    }

    func start() async {
        await refresh()
        startPolling()
        startSSE()
    }

    func stop() {
        pollingTask?.cancel()
        sseTask?.cancel()
        inputRequestTask?.cancel()
    }

    private func refresh() async {
        do {
            let job = try await apiClient.fetchGenerationJob(id: jobID)
            state = .loaded(job)
            handleStatusChange(job.status.value)
        } catch let error as ApiError {
            if state.value == nil { state = .failed(error) }
        } catch {
            if state.value == nil { state = .failed(.unexpectedResponse(status: 0)) }
        }
    }

    /// Mirrors the web job page: a job that just arrived at `awaiting_input`
    /// starts the question fetch; one that left it (answered elsewhere,
    /// expired, cancelled) drops whatever question state was showing rather
    /// than leaving a stale form on screen.
    private func handleStatusChange(_ status: JobStatus?) {
        if status == .awaitingInput {
            if inputRequest == nil, inputRequestTask == nil { loadInputRequest() }
        } else {
            inputRequestTask?.cancel()
            inputRequestTask = nil
            inputRequest = nil
            answerSubmitted = false
        }
    }

    /// A 404 here can mean the SSE frame reporting `awaiting_input` landed
    /// before the input-request row committed, not "there is nothing to
    /// answer" — retried a few times before giving up, same shape as the
    /// web `AwaitingInputPanel`.
    private func loadInputRequest() {
        inputRequestTask?.cancel()
        isLoadingInputRequest = true
        inputRequestError = nil
        inputRequestTask = Task {
            defer { inputRequestTask = nil }
            let maxAttempts = 5
            for attempt in 0..<maxAttempts {
                guard !Task.isCancelled else { return }
                do {
                    let request = try await apiClient.fetchInputRequest(jobID: jobID)
                    inputRequest = request
                    isLoadingInputRequest = false
                    return
                } catch ApiError.notFound {
                    if attempt < maxAttempts - 1 {
                        try? await Task.sleep(nanoseconds: 500_000_000)
                        continue
                    }
                    // Gave up on a lagging row, not a real failure — the next
                    // poll tick (5s) retries `handleStatusChange` from scratch.
                    isLoadingInputRequest = false
                    return
                } catch let error as ApiError {
                    inputRequestError = error.fallbackMessage
                    isLoadingInputRequest = false
                    return
                } catch {
                    inputRequestError = L10n.t("jobPage.awaitingInputLoadError")
                    isLoadingInputRequest = false
                    return
                }
            }
            isLoadingInputRequest = false
        }
    }

    func submitAnswer(_ answers: [String: AnswerValue]) async {
        guard let inputRequest else { return }
        isSubmittingAnswer = true
        inputRequestError = nil
        defer { isSubmittingAnswer = false }
        do {
            let items = inputRequest.questions.compactMap { question -> JobAnswerItem? in
                guard let value = answers[question.id] else { return nil }
                return JobAnswerItem(questionID: question.id, value: value)
            }
            let job = try await apiClient.answerJob(jobID: jobID, answers: items)
            state = .loaded(job)
            answerSubmitted = true
            handleStatusChange(job.status.value)
        } catch let error as ApiError {
            inputRequestError = error.fallbackMessage
        } catch {
            inputRequestError = L10n.t("jobPage.awaitingInputSubmitError")
        }
    }

    private func startPolling() {
        pollingTask?.cancel()
        pollingTask = Task {
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 5_000_000_000)
                guard !Task.isCancelled else { return }
                await refresh()
                if state.value?.status.value?.isTerminal == true { return }
            }
        }
    }

    private func startSSE() {
        sseTask?.cancel()
        sseTask = Task {
            do {
                for try await event in await eventStreamClient.jobEvents(jobID: jobID) {
                    applyStreamEvent(event)
                    if !event.isThinking, event.status.value?.isTerminal == true {
                        await refresh() // 终态时补一次完整 GET，拿到 output_url/actual_credits 等流事件里没有的字段
                        return
                    }
                }
            } catch {
                // SSE 断了不额外处理——轮询循环仍在跑，5 秒内会对齐状态。
            }
        }
    }

    /// 阶段事件带 sequence，用来推进进度；思考帧没有 sequence，只累加
    /// `liveThinking`，不当阶段。完整字段等终态 GET 补上。
    private func applyStreamEvent(_ event: JobStreamEvent) {
        if event.isThinking {
            let increment = event.thinking ?? ""
            guard !increment.isEmpty else { return }
            if let nodeId = event.nodeId, let current = liveThinkingNodeId, current != nodeId {
                liveThinking = increment
            } else {
                liveThinking += increment
            }
            liveThinkingNodeId = event.nodeId ?? liveThinkingNodeId
            return
        }
        guard case .loaded(let job) = state, let sequence = event.sequence, sequence > lastAppliedSequence else { return }
        lastAppliedSequence = sequence
        if let nodeId = event.nodeId, let current = liveThinkingNodeId, current != nodeId {
            liveThinking = ""
            liveThinkingNodeId = nodeId
        }
        state = .loaded(job.withStreamProgress(status: event.status, progress: event.progress))
        handleStatusChange(event.status.value)
    }

    func cancel() async {
        guard state.value?.status.value?.isCancellable == true else { return }
        isCancelling = true
        actionError = nil
        defer { isCancelling = false }
        do {
            state = .loaded(try await apiClient.cancelGenerationJob(id: jobID))
        } catch let error as ApiError {
            actionError = error.fallbackMessage
        } catch {
            actionError = L10n.t("settingsPage.saveFailed")
        }
    }

    func retry() async {
        guard state.value?.status.value?.isTerminal == true else { return }
        isRetrying = true
        actionError = nil
        defer { isRetrying = false }
        do {
            let key = UUID().uuidString
            let job = try await apiClient.retryGenerationJob(id: jobID, idempotencyKey: key)
            retriedJobID = job.id
        } catch let error as ApiError {
            actionError = error.fallbackMessage
        } catch {
            actionError = L10n.t("settingsPage.saveFailed")
        }
    }
}
