import SwiftUI
import ZaolangKit

/// 创作 Tab 顶部常驻浮条（`roadmap.md`"进行中任务浮条"一节）：非终态任务显示进度，
/// 终态后变成结果提示，点掉或 8 秒后自动消失。用 `TimelineView` 周期性重新求值
/// "距终态是否已经过 8 秒"，不需要额外的定时器状态。
struct CreateJobBanner: View {
    @Environment(AppEnvironment.self) private var environment
    let onOpen: (String) -> Void

    @State private var dismissedJobIDs: Set<String> = []

    var body: some View {
        TimelineView(.periodic(from: .now, by: 1)) { context in
            if let job = relevantJob(now: context.date) {
                banner(job)
            }
        }
    }

    /// 优先显示还在跑的任务；没有的话看是否有刚进终态（8 秒内）且没被用户点掉的任务。
    private func relevantJob(now: Date) -> GenerationJobResponse? {
        if let running = environment.activeJobs.first(where: { !dismissedJobIDs.contains($0.id) }) {
            return running
        }
        return environment.trackedJobs.values.first { job in
            guard !dismissedJobIDs.contains(job.id), let finishedAt = job.finishedAt else { return false }
            return now.timeIntervalSince(finishedAt) < 8
        }
    }

    private func banner(_ job: GenerationJobResponse) -> some View {
        let status = job.status.value
        return Button {
            onOpen(job.id)
        } label: {
            HStack(spacing: 10) {
                icon(for: status)
                VStack(alignment: .leading, spacing: 2) {
                    Text(statusLabel(status)).font(.footnote.weight(.semibold))
                    if status?.isTerminal != true {
                        ProgressView(value: Double(job.progress), total: 100)
                            .tint(Color.zl.primary)
                    }
                }
                Spacer()
                if status?.isTerminal == true {
                    Button {
                        dismissedJobIDs.insert(job.id)
                    } label: {
                        Image(systemName: "xmark")
                    }
                    .buttonStyle(.plain)
                    .frame(width: 32, height: 32)
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(.bar)
        }
        .buttonStyle(.plain)
    }

    @ViewBuilder
    private func icon(for status: JobStatus?) -> some View {
        switch status {
        case .succeeded:
            Image(systemName: "checkmark.circle.fill").foregroundStyle(Color.zl.success)
        case .failed, .expired:
            Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(Color.zl.danger)
        case .cancelled:
            Image(systemName: "slash.circle").foregroundStyle(Color.zl.textMuted)
        default:
            ProgressView().controlSize(.small)
        }
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
