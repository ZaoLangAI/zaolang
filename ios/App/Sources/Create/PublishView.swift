import SwiftUI
import ZaolangKit

/// 发布页，对应 `(site)/publish/[draftId]/page.tsx`。
struct PublishView: View {
    @Environment(AppEnvironment.self) private var environment
    let draftID: String
    let onPublished: (String) -> Void

    @State private var viewModel: PublishViewModel?

    var body: some View {
        content
            .navigationTitle(L10n.t("publishPage.title"))
            .navigationBarTitleDisplayMode(.inline)
            .task {
                if viewModel == nil {
                    viewModel = PublishViewModel(draftID: draftID, apiClient: environment.apiClient)
                }
                await viewModel?.load()
            }
            .onChange(of: viewModel?.publishResult?.workID) { _, workID in
                if let workID { onPublished(workID) }
            }
    }

    @ViewBuilder
    private var content: some View {
        switch viewModel?.loadState ?? .loading {
        case .loading:
            ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
        case .empty:
            EmptyStateView(title: L10n.t("states.notFound"), message: L10n.t("publishPage.draftMissing"))
        case .failed(let error):
            ErrorStateView(error: error) { Task { await viewModel?.load() } }
        case .loaded(let draft):
            form(draft, viewModel!)
        }
    }

    private func form(_ draft: DraftResponse, _ viewModel: PublishViewModel) -> some View {
        Form {
            Section {
                RemoteImage(url: draft.outputURL.flatMap(URL.init), aspectRatio: 16.0 / 9.0)
                    .zlCornerRadius(ZLRadius.md)
                    .listRowInsets(EdgeInsets())
            } header: {
                Text(L10n.t("publishPage.coverLabel"))
            }

            Section {
                TextField(L10n.t("publishPage.titleField"), text: Binding(get: { viewModel.title }, set: { viewModel.title = $0 }))
                TextField(
                    L10n.t("publishPage.descriptionField"),
                    text: Binding(get: { viewModel.description }, set: { viewModel.description = $0 }),
                    axis: .vertical
                )
            }

            Section(L10n.t("publishPage.visibilityField")) {
                Picker(L10n.t("publishPage.visibilityField"), selection: Binding(get: { viewModel.visibility }, set: { viewModel.visibility = $0 })) {
                    Text(L10n.t("visibility.public_remixable")).tag(Visibility.publicRemixable)
                    Text(L10n.t("visibility.public_view_only")).tag(Visibility.publicViewOnly)
                    Text(L10n.t("visibility.private")).tag(Visibility.`private`)
                }
            }

            if draft.isRemix, let license = draft.license {
                Section(L10n.t("publishPage.licenseSnapshot")) {
                    Text(license.attributionText).font(.footnote).foregroundStyle(Color.zl.textMuted)
                }
            }

            Section {
                Toggle(isOn: Binding(get: { viewModel.rightsConfirmed }, set: { viewModel.rightsConfirmed = $0 })) {
                    Text(L10n.t("publishPage.rightsConfirm")).font(.footnote)
                }
                Toggle(isOn: Binding(get: { viewModel.aiDisclosureConfirmed }, set: { viewModel.aiDisclosureConfirmed = $0 })) {
                    Text(L10n.t("publishPage.aiLabel")).font(.footnote)
                }
            }

            Section {
                Button {
                    Task { await viewModel.publish() }
                } label: {
                    HStack {
                        Spacer()
                        if viewModel.isPublishing {
                            ProgressView()
                        } else {
                            Text(L10n.t("publishPage.publishNow")).font(.body.weight(.semibold))
                        }
                        Spacer()
                    }
                }
                .disabled(!viewModel.canPublish)

                if let error = viewModel.publishError {
                    Text(error).font(.footnote).foregroundStyle(Color.zl.danger)
                }
            }
        }
    }
}
