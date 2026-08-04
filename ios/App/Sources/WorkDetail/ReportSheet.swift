import SwiftUI
import ZaolangKit

/// 举报表单：`subject_type` 目前只有作品详情这一个入口，固定传 `"work"`（后端还接受
/// `asset`/`user`/`comment`，iOS 没有对应界面，不在这里暴露——YAGNI）。
struct ReportSheet: View {
    let workID: String
    let apiClient: APIClient
    @Environment(\.dismiss) private var dismiss

    @State private var reason: ReportReason = .copyright
    @State private var detail = ""
    @State private var isSubmitting = false
    @State private var submitError: String?
    @State private var didSubmit = false

    var body: some View {
        NavigationStack {
            Form {
                if didSubmit {
                    Section {
                        Text(L10n.t("workPage.reportSubmitted")).foregroundStyle(Color.zl.success)
                    }
                } else {
                    Section(L10n.t("workPage.reportReason")) {
                        Picker(L10n.t("workPage.reportReason"), selection: $reason) {
                            ForEach(ReportReason.allCases, id: \.self) { reason in
                                Text(L10n.t(reason.labelKey)).tag(reason)
                            }
                        }
                        .pickerStyle(.inline)
                        .labelsHidden()
                    }
                    Section {
                        TextField(L10n.t("workPage.reportDetailPlaceholder"), text: $detail, axis: .vertical)
                            .lineLimit(3...6)
                    }
                    if let submitError {
                        Text(submitError).font(.footnote).foregroundStyle(Color.zl.danger)
                    }
                }
            }
            .navigationTitle(L10n.t("workPage.reportTitle"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(L10n.t("actions.close")) { dismiss() }
                }
                if !didSubmit {
                    ToolbarItem(placement: .confirmationAction) {
                        Button(L10n.t("workPage.reportSubmit")) {
                            Task { await submit() }
                        }
                        .disabled(isSubmitting)
                    }
                }
            }
        }
    }

    private func submit() async {
        isSubmitting = true
        submitError = nil
        defer { isSubmitting = false }
        do {
            _ = try await apiClient.createReport(ReportCreateRequest(
                subjectType: "work",
                subjectID: workID,
                reason: reason,
                detail: detail.isEmpty ? nil : detail
            ))
            didSubmit = true
        } catch let error as ApiError {
            submitError = error.fallbackMessage
        } catch {
            submitError = L10n.t("settingsPage.saveFailed")
        }
    }
}

extension ReportReason {
    var labelKey: String {
        switch self {
        case .copyright: "workPage.reportReasonCopyright"
        case .sexualContent: "workPage.reportReasonSexualContent"
        case .violence: "workPage.reportReasonViolence"
        case .hate: "workPage.reportReasonHate"
        case .minorSafety: "workPage.reportReasonMinorSafety"
        case .fraud: "workPage.reportReasonFraud"
        case .other: "workPage.reportReasonOther"
        }
    }
}
