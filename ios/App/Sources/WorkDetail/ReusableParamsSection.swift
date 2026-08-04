import SwiftUI
import UIKit
import ZaolangKit

/// 对应 `components/work/reusable-params.tsx`：只展示许可实际允许带走的字段，
/// 许可禁止衍生时后端给空对象，`ReusableParams.isEmpty` 为真直接不渲染整块。
/// 复制到剪贴板是纯本地操作，不需要登录墙——这条和点赞/收藏不是一类动作。
struct ReusableParamsSection: View {
    let params: ReusableParams
    let version: WorkVersionSummary?

    var body: some View {
        let rows = buildRows()
        if !rows.isEmpty {
            VStack(alignment: .leading, spacing: 12) {
                Text(L10n.t("work.reusable")).font(.subheadline.weight(.semibold))

                VStack(spacing: 0) {
                    ForEach(rows) { row in
                        ParamRow(row: row)
                        if row.id != rows.last?.id {
                            Divider()
                        }
                    }
                }
                .background(Color.zl.surfaceSoft)
                .zlCornerRadius(ZLRadius.sm)
                .overlay {
                    RoundedRectangle.zl(ZLRadius.sm).strokeBorder(Color.zl.border, lineWidth: 1)
                }
            }
        }
    }

    private struct Row: Identifiable {
        let id: String
        let label: String
        let value: String
        let copyValue: String
    }

    private func buildRows() -> [Row] {
        var rows: [Row] = []
        if let prompt = params.prompt, !prompt.isEmpty {
            rows.append(Row(id: "prompt", label: L10n.t("work.prompt"), value: prompt, copyValue: prompt))
        }
        let base = describeBase(params.extra)
        if !base.isEmpty {
            rows.append(Row(id: "base", label: L10n.t("work.baseParams"), value: base, copyValue: base))
        }
        if !params.styleTags.isEmpty {
            let joined = params.styleTags.joined(separator: " · ")
            rows.append(Row(id: "style", label: L10n.t("work.modelStyle"), value: joined, copyValue: joined))
        }
        if let version {
            let value = "v\(version.versionNumber) · \(version.createdAt.formatted(date: .abbreviated, time: .omitted))"
            rows.append(Row(id: "workflow", label: L10n.t("work.workflowVersion"), value: value, copyValue: params.workflowVersionID ?? value))
        } else if let workflowID = params.workflowVersionID {
            rows.append(Row(id: "workflow", label: L10n.t("work.workflowVersion"), value: workflowID, copyValue: workflowID))
        }
        return rows
    }

    private func describeBase(_ extra: [String: JSONValue]) -> String {
        var parts: [String] = []
        if case .number(let seconds)? = extra["duration_seconds"] {
            parts.append("\(Int(seconds))s")
        }
        if case .string(let resolution)? = extra["resolution"] {
            parts.append(resolution)
        }
        if case .number(let fps)? = extra["fps"] {
            parts.append("\(Int(fps))fps")
        }
        if case .string(let aspect)? = extra["aspect_ratio"] {
            parts.append(aspect)
        }
        return parts.joined(separator: " | ")
    }

    private struct ParamRow: View {
        let row: Row
        @State private var copied = false

        var body: some View {
            HStack(alignment: .top, spacing: 12) {
                Text(row.label)
                    .font(.caption)
                    .foregroundStyle(Color.zl.amber)
                    .frame(width: 76, alignment: .leading)
                // `prompt` 值可能是一整段长文本，Dynamic Type 大字号下更不能卡死一行——
                // 允许换行铺满，靠 copy 按钮兜底"看不全就拷走"这条路径。
                Text(row.value)
                    .font(.caption)
                    .foregroundStyle(Color.zl.textMuted)
                Spacer(minLength: 0)
                Button {
                    UIPasteboard.general.string = row.copyValue
                    copied = true
                    Task {
                        try? await Task.sleep(for: .seconds(1.6))
                        copied = false
                    }
                } label: {
                    Image(systemName: copied ? "checkmark" : "doc.on.doc")
                        .foregroundStyle(copied ? Color.zl.success : Color.zl.textMuted)
                        .frame(width: 32, height: 32)
                }
                .buttonStyle(.plain)
                .accessibilityLabel(L10n.t("actions.copy"))
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 10)
        }
    }
}
