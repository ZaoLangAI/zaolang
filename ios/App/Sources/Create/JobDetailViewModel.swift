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

    private var pollingTask: Task<Void, Never>?
    private var sseTask: Task<Void, Never>?
    private var lastAppliedSequence = -1

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
    }

    private func refresh() async {
        do {
            let job = try await apiClient.fetchGenerationJob(id: jobID)
            state = .loaded(job)
        } catch let error as ApiError {
            if state.value == nil { state = .failed(error) }
        } catch {
            if state.value == nil { state = .failed(.unexpectedResponse(status: 0)) }
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
                    if event.status.value?.isTerminal == true {
                        await refresh() // 终态时补一次完整 GET，拿到 output_url/actual_credits 等流事件里没有的字段
                        return
                    }
                }
            } catch {
                // SSE 断了不额外处理——轮询循环仍在跑，5 秒内会对齐状态。
            }
        }
    }

    /// SSE 帧只有 sequence/status/progress/message 四项，先用它做即时进度反馈，
    /// 完整字段（`output_url`/`actual_credits`…）等终态时的那次 GET 补上。
    private func applyStreamEvent(_ event: JobStreamEvent) {
        guard case .loaded(let job) = state, event.sequence > lastAppliedSequence else { return }
        lastAppliedSequence = event.sequence
        state = .loaded(job.withStreamProgress(status: event.status, progress: event.progress))
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
