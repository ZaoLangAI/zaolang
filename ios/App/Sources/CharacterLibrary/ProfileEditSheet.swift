import SwiftUI
import ZaolangKit

/// 改角色名与两段描述；关联了剧本时可「AI 生成」草稿，先填进表单，保存才落库。
struct ProfileEditSheet: View {
    let viewModel: CharacterDetailViewModel

    @Environment(\.dismiss) private var dismiss
    @State private var name: String
    @State private var description: String
    @State private var voiceDescription: String
    @State private var drafting = false
    @State private var saving = false

    init(graph: AssetGraphResponse, viewModel: CharacterDetailViewModel) {
        self.viewModel = viewModel
        _name = State(initialValue: graph.name)
        _description = State(initialValue: graph.description ?? "")
        _voiceDescription = State(initialValue: graph.voiceDescription ?? "")
    }

    var body: some View {
        NavigationStack {
            Form {
                Section(L10n.t("characters.nameLabel")) {
                    TextField(L10n.t("characters.nameLabel"), text: $name)
                }
                Section(L10n.t("characters.descriptionLabel")) {
                    TextField(L10n.t("characters.descriptionLabel"), text: $description, axis: .vertical)
                        .lineLimit(3...8)
                }
                Section(L10n.t("characters.voiceLabel")) {
                    TextField(L10n.t("characters.voiceLabel"), text: $voiceDescription, axis: .vertical)
                        .lineLimit(2...6)
                }
                if !viewModel.scriptLinks.isEmpty {
                    Section {
                        Button {
                            Task {
                                drafting = true
                                defer { drafting = false }
                                guard let draft = await viewModel.describe() else { return }
                                if let text = draft.description { description = text }
                                if let text = draft.voiceDescription { voiceDescription = text }
                            }
                        } label: {
                            HStack(spacing: 6) {
                                if drafting { ProgressView() }
                                Text(L10n.t("characters.describeOpen"))
                            }
                        }
                        .disabled(drafting)
                    } footer: {
                        Text(L10n.t("iosCharacters.describeHint"))
                    }
                }
            }
            .navigationTitle(L10n.t("iosCharacters.editProfile"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(L10n.t("actions.cancel")) { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(L10n.t("actions.save")) {
                        Task {
                            saving = true
                            defer { saving = false }
                            if await viewModel.saveProfile(
                                name: name.trimmingCharacters(in: .whitespacesAndNewlines),
                                description: description,
                                voiceDescription: voiceDescription
                            ) { dismiss() }
                        }
                    }
                    .disabled(saving || name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
        }
    }
}
