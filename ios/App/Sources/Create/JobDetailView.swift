import SwiftUI
import ZaolangKit

/// 任务详情，对应 `(site)/jobs/[jobId]/page.tsx`。取消按钮只在可取消状态出现，
/// 重试只在终态出现；重试成功后把当前屏幕换成新 job id，不停在旧任务上。
struct JobDetailView: View {
    @Environment(AppEnvironment.self) private var environment
    let jobID: String
    let onOpenPublish: (String) -> Void
    let onSwitchToJob: (String) -> Void

    @State private var viewModel: JobDetailViewModel?
    @State private var showCancelConfirm = false

    var body: some View {
        content
            .navigationTitle(L10n.t("jobPage.title"))
            .navigationBarTitleDisplayMode(.inline)
            .task {
                if viewModel == nil {
                    viewModel = JobDetailViewModel(
                        jobID: jobID,
                        apiClient: environment.apiClient,
                        eventStreamClient: environment.eventStreamClient
                    )
                }
                await viewModel?.start()
            }
            .onDisappear { viewModel?.stop() }
            .onChange(of: viewModel?.retriedJobID) { _, newJobID in
                if let newJobID { onSwitchToJob(newJobID) }
            }
            .confirmationDialog(L10n.t("jobPage.cancelConfirm"), isPresented: $showCancelConfirm, titleVisibility: .visible) {
                Button(L10n.t("job.cancel"), role: .destructive) {
                    Task { await viewModel?.cancel() }
                }
                Button(L10n.t("actions.cancel"), role: .cancel) {}
            }
    }

    @ViewBuilder
    private var content: some View {
        switch viewModel?.state ?? .loading {
        case .loading:
            ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
        case .empty:
            EmptyStateView(title: L10n.t("states.notFound"), message: L10n.t("jobPage.title"))
        case .failed(let error):
            ErrorStateView(error: error) { Task { await viewModel?.start() } }
        case .loaded(let job):
            body(job)
        }
    }

    private func body(_ job: GenerationJobResponse) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                Text(L10n.t("jobPage.subtitle", ["id": job.id]))
                    .font(.caption)
                    .foregroundStyle(Color.zl.textMuted)

                statusSection(job)

                if let outputURL = job.outputURL, job.status.value == .succeeded {
                    RemoteImage(url: URL(string: outputURL), aspectRatio: 16.0 / 9.0)
                        .zlCornerRadius(ZLRadius.md)
                }

                creditsSection(job)

                if job.status.value == .failed {
                    failedSection(job)
                }

                eventLog(job)
            }
            .padding(16)
            .padding(.bottom, 96)
        }
        .safeAreaInset(edge: .bottom) { bottomBar(job) }
    }

    private func statusSection(_ job: GenerationJobResponse) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(statusLabel(job.status.value)).font(.title3.weight(.semibold))
            if job.status.value?.isTerminal != true {
                ProgressView(value: Double(job.progress), total: 100)
                Text(L10n.t("job.progress", ["percent": job.progress]))
                    .font(.caption)
                    .foregroundStyle(Color.zl.textMuted)
            }
            if job.status.value == nil || job.progress == 0, job.status.value?.isTerminal != true {
                Text(L10n.t("jobPage.waiting")).font(.caption).foregroundStyle(Color.zl.textMuted)
            }
        }
    }

    private func creditsSection(_ job: GenerationJobResponse) -> some View {
        HStack(spacing: 16) {
            if job.status.value?.isTerminal != true {
                Text(L10n.t("jobPage.creditsReserved", ["count": job.reservedCredits]))
            } else if let actual = job.actualCredits {
                Text(L10n.t("jobPage.creditsSettled", ["count": actual]))
            } else {
                Text(L10n.t("jobPage.creditsRefunded", ["count": job.reservedCredits]))
            }
        }
        .font(.footnote)
        .foregroundStyle(Color.zl.textMuted)
    }

    private func failedSection(_ job: GenerationJobResponse) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(L10n.t("jobPage.failedTitle")).font(.subheadline.weight(.semibold))
            Text(L10n.t("jobPage.failedHint")).font(.caption).foregroundStyle(Color.zl.textMuted)
            if let code = job.failureCode {
                Text(L10n.t("job.errorCode", ["code": code])).font(.caption2).foregroundStyle(Color.zl.textMuted)
            }
        }
        .padding(12)
        .background(Color.zl.danger.opacity(0.08))
        .zlCornerRadius(ZLRadius.md)
    }

    private func eventLog(_ job: GenerationJobResponse) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            if !job.events.isEmpty {
                Text(L10n.t("jobPage.eventLog")).font(.subheadline.weight(.semibold))
                ForEach(job.events) { event in
                    HStack {
                        Text(event.message).font(.caption)
                        Spacer()
                        Text(event.createdAt.formatted(date: .omitted, time: .standard))
                            .font(.caption2)
                            .foregroundStyle(Color.zl.textMuted)
                    }
                }
            }
        }
    }

    @ViewBuilder
    private func bottomBar(_ job: GenerationJobResponse) -> some View {
        VStack(spacing: 8) {
            if let error = viewModel?.actionError {
                Text(error).font(.caption).foregroundStyle(Color.zl.danger)
            }
            HStack(spacing: 12) {
                if job.status.value?.isCancellable == true {
                    Button(role: .destructive) {
                        showCancelConfirm = true
                    } label: {
                        Text(L10n.t("job.cancel")).frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.bordered)
                    .disabled(viewModel?.isCancelling ?? false)
                }
                if job.status.value?.isTerminal == true, job.status.value != .succeeded {
                    Button {
                        Task { await viewModel?.retry() }
                    } label: {
                        Text(L10n.t("job.retry")).frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(viewModel?.isRetrying ?? false)
                }
                if job.status.value == .succeeded, let draftID = job.draftID {
                    Button {
                        onOpenPublish(draftID)
                    } label: {
                        Text(L10n.t("job.publish")).frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                }
            }
        }
        .padding(.horizontal, 16)
        .padding(.top, 8)
        .background(.bar)
    }

    private func statusLabel(_ status: JobStatus?) -> String {
        switch status {
        case .created: L10n.t("job.created")
        case .queued: L10n.t("job.queued")
        case .submitted: L10n.t("job.submitted")
        case .running: L10n.t("job.running")
        case .succeeded: L10n.t("job.succeeded")
        case .failed: L10n.t("job.failed")
        case .cancelled: L10n.t("job.cancelled")
        case .expired: L10n.t("job.expired")
        case nil: L10n.t("job.queued")
        }
    }
}
