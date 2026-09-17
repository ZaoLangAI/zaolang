import SwiftUI
import ZaolangKit

/// The follow-up question form for a job parked at `awaiting_input` —
/// mirrors the web `AwaitingInputPanel` (single/multi choice + free text,
/// required-answer gating, no re-billing on answer). Rendered inline on the
/// job detail screen: before this, iOS only showed the `awaiting_input`
/// status label with no way to actually answer, so the job (and its
/// reservation) sat stuck until it expired.
struct AwaitingInputSection: View {
    let request: JobInputRequestResponse
    let isSubmitting: Bool
    let error: String?
    let submitted: Bool
    let onSubmit: ([String: AnswerValue]) -> Void

    @State private var answers: [String: AnswerValue] = [:]

    private var missingRequired: Bool {
        request.questions.contains { question in
            guard question.required else { return false }
            guard let value = answers[question.id] else { return true }
            return value.isEmpty
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 6) {
                Image(systemName: "sparkles").foregroundStyle(Color.zl.primary)
                Text(L10n.t("jobPage.awaitingInputTitle")).font(.subheadline.weight(.semibold))
            }
            Text(L10n.t("jobPage.awaitingInputIntro"))
                .font(.caption)
                .foregroundStyle(Color.zl.textMuted)

            ForEach(request.questions) { question in
                questionView(question)
            }

            if let error {
                Text(error).font(.caption).foregroundStyle(Color.zl.danger)
            }

            Button {
                onSubmit(answers)
            } label: {
                HStack {
                    if isSubmitting { ProgressView() }
                    Text(
                        submitted
                            ? L10n.t("jobPage.awaitingInputSubmitted")
                            : L10n.t("jobPage.awaitingInputSubmit")
                    )
                }
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .disabled(missingRequired || submitted || isSubmitting)
        }
        .padding(12)
        .background(Color.zl.primary.opacity(0.06))
        .zlCornerRadius(ZLRadius.md)
    }

    @ViewBuilder
    private func questionView(_ question: JobInputQuestion) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(questionLabel(question)).font(.footnote.weight(.medium))
            switch question.kind {
            case .singleChoice:
                VStack(spacing: 4) {
                    ForEach(question.options) { option in
                        optionRow(
                            label: option.label,
                            selected: singleSelection(question.id) == option.value,
                            multi: false
                        ) {
                            answers[question.id] = .text(option.value)
                        }
                    }
                }
            case .multiChoice:
                VStack(spacing: 4) {
                    ForEach(question.options) { option in
                        let selected = multiSelection(question.id).contains(option.value)
                        optionRow(label: option.label, selected: selected, multi: true) {
                            var current = multiSelection(question.id)
                            if selected {
                                current.removeAll { $0 == option.value }
                            } else {
                                current.append(option.value)
                            }
                            answers[question.id] = .choices(current)
                        }
                    }
                }
            case .freeText:
                TextField(
                    question.prompt,
                    text: Binding(
                        get: { textValue(question.id) },
                        set: { answers[question.id] = .text($0) }
                    )
                )
                .textFieldStyle(.roundedBorder)
            }
        }
    }

    private func questionLabel(_ question: JobInputQuestion) -> String {
        question.required
            ? "\(question.prompt)（\(L10n.t("jobPage.awaitingInputRequired"))）"
            : question.prompt
    }

    private func singleSelection(_ questionID: String) -> String? {
        if case .text(let value) = answers[questionID] { return value }
        return nil
    }

    private func multiSelection(_ questionID: String) -> [String] {
        if case .choices(let values) = answers[questionID] { return values }
        return []
    }

    private func textValue(_ questionID: String) -> String {
        if case .text(let value) = answers[questionID] { return value }
        return ""
    }

    private func optionRow(
        label: String,
        selected: Bool,
        multi: Bool,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            HStack {
                Image(
                    systemName: selected
                        ? (multi ? "checkmark.square.fill" : "largecircle.fill.circle")
                        : (multi ? "square" : "circle")
                )
                .foregroundStyle(selected ? Color.zl.primary : Color.zl.textMuted)
                Text(label).foregroundStyle(Color.zl.text)
                Spacer()
            }
            .padding(.vertical, 6)
            .padding(.horizontal, 10)
            .background(selected ? Color.zl.primary.opacity(0.08) : Color.clear)
            .zlCornerRadius(ZLRadius.sm)
        }
        .buttonStyle(.plain)
    }
}
