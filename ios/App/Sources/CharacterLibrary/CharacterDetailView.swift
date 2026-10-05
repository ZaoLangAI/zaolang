import SwiftUI
import ZaolangKit

/// 一个角色的管理页（只读为主）：造型 | 音色。造型按派生关系缩进排列，同一张图的多个版本
/// 折叠为一格（`CharacterGraphModel`）；候选图可定稿，音色可试听 / 设默认 / 生成试听。
struct CharacterDetailView: View {
    let characterID: String

    @Environment(AppEnvironment.self) private var environment
    @Environment(\.openURL) private var openURL
    @State private var viewModel: CharacterDetailViewModel?
    @State private var tab: Tab = .looks
    @State private var viewing: AssetEntryView?
    @State private var editing = false
    @State private var player = VoicePlayer()

    enum Tab: Hashable { case looks, voices }

    init(characterID: String) {
        self.characterID = characterID
    }

    var body: some View {
        content
            .navigationTitle(viewModel?.graph?.name ?? L10n.t("characters.manageEyebrow"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                if viewModel?.graph != nil {
                    ToolbarItem(placement: .topBarTrailing) {
                        Button(L10n.t("iosCharacters.editProfile")) { editing = true }
                    }
                }
            }
            .task {
                if viewModel == nil {
                    viewModel = CharacterDetailViewModel(characterID: characterID, apiClient: environment.apiClient)
                }
                await viewModel?.load()
            }
            .refreshable { await viewModel?.load() }
            .onDisappear { player.stop() }
            .sheet(item: $viewing) { entry in
                if let viewModel, let graph = viewModel.graph {
                    EntryViewerSheet(graph: graph, entry: entry, viewModel: viewModel)
                }
            }
            .sheet(isPresented: $editing) {
                if let viewModel, let graph = viewModel.graph {
                    ProfileEditSheet(graph: graph, viewModel: viewModel)
                }
            }
            .alert(
                viewModel?.message ?? "",
                isPresented: Binding(
                    get: { viewModel?.message != nil },
                    set: { if !$0 { viewModel?.message = nil } }
                )
            ) {
                Button(L10n.t("actions.confirm"), role: .cancel) { viewModel?.message = nil }
            }
    }

    @ViewBuilder
    private var content: some View {
        switch viewModel?.state ?? .loading {
        case .loading:
            VStack(spacing: 12) {
                ForEach(0..<3, id: \.self) { _ in
                    RoundedRectangle.zl(ZLRadius.md).fill(Color.zl.skeleton).zlSkeletonPulse().frame(height: 120)
                }
            }
            .padding(16)
        case .failed(let error):
            ErrorStateView(error: error) { Task { await viewModel?.load() } }
        case .empty:
            EmptyView()
        case .loaded(let graph):
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    header(graph)
                    Picker("", selection: $tab) {
                        Text(L10n.t("assetGraph.tabLooks", ["count": graph.variants.count])).tag(Tab.looks)
                        Text(L10n.t("assetGraph.tabVoices", ["count": graph.voices.count])).tag(Tab.voices)
                    }
                    .pickerStyle(.segmented)
                    .accessibilityLabel(L10n.t("assetGraph.tabsLabel"))
                    if tab == .looks { looks(graph) } else { voices(graph) }
                    webFooter
                }
                .padding(16)
            }
        }
    }

    private func header(_ graph: AssetGraphResponse) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            if let description = graph.description, !description.isEmpty {
                Text(description).font(.subheadline).foregroundStyle(Color.zl.textMuted)
            }
            if let voice = graph.voiceDescription, !voice.isEmpty {
                Text("\(L10n.t("characters.voiceLabel")): \(voice)").font(.caption).foregroundStyle(Color.zl.textMuted)
            }
        }
    }

    @ViewBuilder
    private func looks(_ graph: AssetGraphResponse) -> some View {
        let rows = CharacterGraphModel.lookRows(graph)
        let versions = CharacterGraphModel.versionIndex(graph).versions
        if rows.allSatisfy({ $0.heads.isEmpty }) {
            Text(L10n.t("iosCharacters.noLooks")).font(.subheadline).foregroundStyle(Color.zl.textMuted)
        }
        ForEach(rows) { row in
            LookCard(row: row, versions: versions, anchorEntryID: graph.anchorEntryID) { viewing = $0 }
                .padding(.leading, CGFloat(min(row.depth, 3)) * 16)
        }
    }

    @ViewBuilder
    private func voices(_ graph: AssetGraphResponse) -> some View {
        if graph.voices.isEmpty {
            Text(L10n.t("iosCharacters.noVoices")).font(.subheadline).foregroundStyle(Color.zl.textMuted)
        }
        let lookNames = Dictionary(uniqueKeysWithValues: graph.variants.map { ($0.id, $0.name) })
        ForEach(graph.voices) { voice in
            if let viewModel {
                VoiceRow(
                    voice: voice,
                    lookNames: voice.lookIDs.compactMap { lookNames[$0] },
                    pending: graph.pending.contains { $0.targetVoiceID == voice.id },
                    player: player,
                    viewModel: viewModel
                )
            }
        }
    }

    private var webFooter: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(L10n.t("iosCharacters.manageOnWebHint")).font(.caption).foregroundStyle(Color.zl.textMuted)
            Button(L10n.t("iosCharacters.manageOnWeb")) {
                if let url = URL(string: "\(AppConfig.webBaseURLString)/create/characters/\(characterID)") {
                    openURL(url)
                }
            }
            .buttonStyle(.bordered)
        }
        .padding(.top, 8)
    }
}

/// 一个造型：名称、属性行、派生来源，以及（版本折叠后的）图片网格。
struct LookCard: View {
    let row: CharacterGraphModel.LookRow
    let versions: [String: [AssetEntryView]]
    let anchorEntryID: String?
    let onOpen: (AssetEntryView) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 6) {
                Text(row.look.name).font(.subheadline.weight(.semibold)).foregroundStyle(Color.zl.text)
                if row.look.isDefault { badge(L10n.t("assetGraph.defaultBadge"), tint: Color.zl.primary) }
            }
            ForEach(Array(row.parents.enumerated()), id: \.offset) { _, parent in
                HStack(spacing: 6) {
                    Circle().fill(Color.zl.relation(parent.relations.first ?? "custom")).frame(width: 8, height: 8)
                        .accessibilityHidden(true)
                    Text(L10n.t("assetGraph.derivedFrom", ["names": parent.name]))
                    Text(CharacterGraphModel.relationText(parent.relations, label: parent.label))
                        .foregroundStyle(Color.zl.text)
                }
                .font(.caption)
                .foregroundStyle(Color.zl.textMuted)
            }
            let attributes = CharacterGraphModel.attributeRows(row.look)
            if !attributes.isEmpty {
                VStack(alignment: .leading, spacing: 2) {
                    ForEach(Array(attributes.enumerated()), id: \.offset) { _, attribute in
                        HStack(alignment: .top, spacing: 8) {
                            Text(attribute.label).foregroundStyle(Color.zl.textMuted).frame(width: 64, alignment: .leading)
                            Text(attribute.value).foregroundStyle(Color.zl.text)
                        }
                        .font(.caption)
                    }
                }
            }
            if row.heads.isEmpty {
                Text(L10n.t("assetGraph.emptyLook")).font(.caption).foregroundStyle(Color.zl.textMuted)
            } else {
                LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 8), count: 3), spacing: 8) {
                    ForEach(row.heads) { entry in
                        Button { onOpen(entry) } label: { tile(entry) }
                            .buttonStyle(.plain)
                            .accessibilityLabel(L10n.t("assetVariants.type.\(entry.entryType)"))
                    }
                }
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.zl.surface)
        .zlCornerRadius(ZLRadius.md)
    }

    private func tile(_ entry: AssetEntryView) -> some View {
        let group = versions[entry.id] ?? [entry]
        return ZStack(alignment: .topLeading) {
            RemoteImage(url: entry.url.flatMap(URL.init(string:)), aspectRatio: 1)
                .opacity(entry.isCandidate ? 0.7 : 1)
            if group.contains(where: { $0.id == anchorEntryID }) {
                badge(L10n.t("assetVariants.anchor"), tint: Color.zl.primary).padding(4)
            } else if entry.isCandidate {
                badge(L10n.t("assetVariants.candidate"), tint: Color.zl.textMuted).padding(4)
            }
            if group.count > 1 {
                badge(L10n.t("assetGraph.versionBadge", ["count": group.count]), tint: Color.zl.text)
                    .padding(4)
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomTrailing)
            }
        }
        .zlCornerRadius(ZLRadius.sm)
    }

    private func badge(_ text: String, tint: Color) -> some View {
        Text(text)
            .font(.caption2.weight(.medium))
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .foregroundStyle(tint)
            .background(Color.zl.surface.opacity(0.9))
            .zlCornerRadius(ZLRadius.sm)
    }
}
