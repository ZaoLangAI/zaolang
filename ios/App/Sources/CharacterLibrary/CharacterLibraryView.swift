import SwiftUI
import ZaolangKit

/// 角色库列表：每个角色一行（代表图、名称、描述、音色描述），点进角色管理页。
/// 新建角色与图片编辑在网页端（`zaolang-ios-client` › reference-roadmap）。
struct CharacterLibraryView: View {
    @Environment(AppEnvironment.self) private var environment
    @Environment(\.openURL) private var openURL
    @State private var viewModel: CharacterLibraryViewModel?

    var body: some View {
        content
            .navigationTitle(L10n.t("characters.eyebrow"))
            .navigationBarTitleDisplayMode(.inline)
            .task {
                if viewModel == nil { viewModel = CharacterLibraryViewModel(apiClient: environment.apiClient) }
                await viewModel?.load()
            }
            .refreshable { await viewModel?.load() }
    }

    @ViewBuilder
    private var content: some View {
        switch viewModel?.state ?? .loading {
        case .loading:
            List {
                ForEach(0..<4, id: \.self) { _ in
                    RoundedRectangle.zl(ZLRadius.sm).fill(Color.zl.skeleton).zlSkeletonPulse().frame(height: 72)
                }
            }
            .listStyle(.plain)
        case .failed(let error):
            ErrorStateView(error: error) { Task { await viewModel?.load() } }
        case .empty:
            EmptyStateView(
                title: L10n.t("characters.emptyTitle"),
                message: L10n.t("characters.emptyHint"),
                actionTitle: L10n.t("iosCharacters.manageOnWeb")
            ) {
                if let url = URL(string: "\(AppConfig.webBaseURLString)/create/characters") { openURL(url) }
            }
        case .loaded(let characters):
            List(characters) { character in
                NavigationLink(value: CreateRoute.characterDetail(characterID: character.id)) {
                    row(character)
                }
            }
            .listStyle(.plain)
        }
    }

    private func row(_ character: CharacterResponse) -> some View {
        HStack(alignment: .top, spacing: 12) {
            RemoteImage(url: character.heroURL.flatMap(URL.init(string:)), aspectRatio: 1)
                .frame(width: 64, height: 64)
                .zlCornerRadius(ZLRadius.sm)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 4) {
                Text(character.name).font(.subheadline.weight(.semibold)).foregroundStyle(Color.zl.text)
                if let description = character.description, !description.isEmpty {
                    Text(description).font(.caption).foregroundStyle(Color.zl.textMuted).lineLimit(2)
                }
                if let voice = character.voiceDescription, !voice.isEmpty {
                    Text("\(L10n.t("characters.voiceLabel")): \(voice)")
                        .font(.caption2).foregroundStyle(Color.zl.textMuted).lineLimit(1)
                }
            }
        }
        .padding(.vertical, 4)
    }
}
