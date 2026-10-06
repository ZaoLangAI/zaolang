import SwiftUI
import ZaolangKit

/// 一张角色 / 场景 / 道具卡的工作区（只读为主）：创作（资产板）| 造型 / 变体 / 状态图谱 | 音色（仅角色）。
/// 资产板按槽位显示完备度与机位覆盖，候选可定稿、主槽位可快速生成；图谱按派生关系缩进排列，
/// 同一张图的多个版本折叠为一格（`AssetGraphModel`）。其余编辑在网页端继续。
struct AssetDetailView: View {
    let kind: AssetCardKind
    let cardID: String

    @Environment(AppEnvironment.self) private var environment
    @Environment(\.openURL) private var openURL
    @State private var viewModel: AssetDetailViewModel?
    @State private var tab: Tab = .create
    @State private var variantID: String?
    @State private var openSlot: OpenSlot?
    @State private var viewing: AssetEntryView?
    @State private var editing = false
    @State private var player = VoicePlayer()

    enum Tab: Hashable { case create, graph, voices }

    struct OpenSlot: Identifiable {
        let variantID: String
        let slotID: String
        var id: String { AssetDetailViewModel.slotKey(variantID: variantID, slotID: slotID) }
    }

    /// `variantID` opens that look / variant first (a notification's `target_variant_id`).
    init(kind: AssetCardKind, cardID: String, variantID: String? = nil) {
        self.kind = kind
        self.cardID = cardID
        _variantID = State(initialValue: variantID)
    }

    var body: some View {
        content
            .navigationTitle(viewModel?.graph?.name ?? L10n.t(AssetSlots.titleKey(kind)))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                if kind == .character, viewModel?.graph != nil {
                    ToolbarItem(placement: .topBarTrailing) {
                        Button(L10n.t("iosCharacters.editProfile")) { editing = true }
                    }
                }
            }
            .task {
                if viewModel == nil {
                    viewModel = AssetDetailViewModel(kind: kind, cardID: cardID, environment: environment)
                }
                await viewModel?.load()
            }
            .refreshable { await viewModel?.load() }
            .onDisappear { player.stop() }
            .sheet(item: $openSlot) { slot in
                if let viewModel {
                    SlotSheet(variantID: slot.variantID, slotID: slot.slotID, viewModel: viewModel)
                }
            }
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
                        Text(L10n.t("assetWorkspace.tabCreate")).tag(Tab.create)
                        Text(L10n.t("assetWorkspace.tabGraph.\(kind.rawValue)", ["count": graph.variants.count])).tag(Tab.graph)
                        if kind == .character {
                            Text(L10n.t("assetGraph.tabVoices", ["count": graph.voices.count])).tag(Tab.voices)
                        }
                    }
                    .pickerStyle(.segmented)
                    .accessibilityLabel(L10n.t("assetGraph.tabsLabel"))
                    switch tab {
                    case .create: board(graph)
                    case .graph: looks(graph)
                    case .voices: voices(graph)
                    }
                    webFooter(graph)
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

    /// The look / variant the board shows: the picked one, else the default.
    private func currentVariant(_ graph: AssetGraphResponse) -> AssetVariantView? {
        graph.variants.first { $0.id == variantID }
            ?? graph.variants.first(where: \.isDefault)
            ?? graph.variants.first
    }

    @ViewBuilder
    private func board(_ graph: AssetGraphResponse) -> some View {
        if let variant = currentVariant(graph) {
            if graph.variants.count > 1 {
                Picker(L10n.t("assetWorkspace.variantsLabel.\(kind.rawValue)"), selection: Binding(
                    get: { variant.id },
                    set: { variantID = $0 }
                )) {
                    ForEach(graph.variants) { option in
                        Text(option.name).tag(option.id)
                    }
                }
                .pickerStyle(.menu)
            }
            AssetSlotBoard(
                kind: kind,
                graph: graph,
                variant: variant,
                generatingSlot: viewModel?.generatingSlot
            ) { state in
                openSlot = OpenSlot(variantID: variant.id, slotID: state.slot.id)
            }
        } else {
            Text(L10n.t("assetWorkspace.noVariants")).font(.subheadline).foregroundStyle(Color.zl.textMuted)
        }
    }

    @ViewBuilder
    private func looks(_ graph: AssetGraphResponse) -> some View {
        let rows = AssetGraphModel.lookRows(graph)
        let versions = AssetGraphModel.versionIndex(graph).versions
        if rows.isEmpty {
            Text(L10n.t("assetWorkspace.noVariants")).font(.subheadline).foregroundStyle(Color.zl.textMuted)
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

    private func webFooter(_ graph: AssetGraphResponse) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(L10n.t("iosAssets.continueOnWebHint")).font(.caption).foregroundStyle(Color.zl.textMuted)
            Button {
                if let url = AssetSlots.webURL(kind, cardID: cardID, variantID: currentVariant(graph)?.id) {
                    openURL(url)
                }
            } label: {
                Label(L10n.t("iosAssets.continueOnWeb"), systemImage: "arrow.up.right.square")
            }
            .buttonStyle(.bordered)
        }
        .padding(.top, 8)
    }
}

/// 一个造型：名称、属性行、派生来源，以及（版本折叠后的）图片网格。
struct LookCard: View {
    let row: AssetGraphModel.LookRow
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
                    Text(AssetGraphModel.relationText(parent.relations, label: parent.label))
                        .foregroundStyle(Color.zl.text)
                }
                .font(.caption)
                .foregroundStyle(Color.zl.textMuted)
            }
            let attributes = AssetGraphModel.attributeRows(row.look)
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
