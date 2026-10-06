import Foundation
import ZaolangKit

/// 卡片管理图（角色造型 / 场景变体 / 道具状态）在手机上的形态：不画画布，按派生关系排成缩进列表
/// （与网页窄屏的 `asset-graph-outline.tsx` 同一规则）。同一张图的多个版本——调整修改
/// 产出（`edit` 关系）与同一槽位的候选——折叠成一个图片格，与网页 `versions.ts` 同一规则：
/// 版本不在关系图里单独出现。
enum AssetGraphModel {
    struct LookRow: Identifiable {
        let look: AssetVariantView
        let depth: Int
        /// 指向这个造型的造型级关系：(来源造型名, 关系)。
        let parents: [(name: String, relations: [String], label: String?)]
        /// 每组版本只留一个代表图（锚点 > 已定稿 > 最新）。
        let heads: [AssetEntryView]

        var id: String { look.id }
    }

    static let slotTypes: Set<String> = [
        "identity_portrait", "character_sheet", "view", "expression_sheet", "master",
    ]

    static func slotKey(_ entry: AssetEntryView, lookID: String) -> String? {
        guard slotTypes.contains(entry.entryType) else { return nil }
        let scope = entry.entryType == "identity_portrait" ? "*" : lookID
        let view = entry.entryType == "view" ? (entry.view ?? "") : ""
        let expressions = entry.entryType == "expression_sheet" ? entry.expressions.sorted().joined(separator: ",") : ""
        return "\(scope)|\(entry.entryType)|\(view)|\(expressions)"
    }

    /// 每个图片 id → 它所在版本组的代表图 id；代表图 id → 组内全部版本（代表图在前，其余按新到旧）。
    static func versionIndex(_ graph: AssetGraphResponse) -> (headOf: [String: String], versions: [String: [AssetEntryView]]) {
        var parent: [String: String] = [:]
        func find(_ id: String) -> String {
            var root = id
            while let next = parent[root], next != root { root = next }
            parent[id] = root
            return root
        }
        func union(_ a: String, _ b: String) {
            guard parent[a] != nil, parent[b] != nil else { return }
            parent[find(a)] = find(b)
        }
        var byID: [String: AssetEntryView] = [:]
        var order: [String: Int] = [:]
        var slots: [String: String] = [:]
        for look in graph.variants {
            for entry in look.entries {
                parent[entry.id] = entry.id
                byID[entry.id] = entry
                order[entry.id] = order.count
                guard let key = slotKey(entry, lookID: look.id) else { continue }
                if let first = slots[key] { union(entry.id, first) } else { slots[key] = entry.id }
            }
        }
        for edge in graph.edges where edge.level == "entry" && edge.relations.contains("edit") {
            union(edge.sourceID, edge.targetID)
        }
        var groups: [String: [AssetEntryView]] = [:]
        for id in byID.keys.sorted(by: { (order[$0] ?? 0) < (order[$1] ?? 0) }) {
            groups[find(id), default: []].append(byID[id]!)
        }
        var headOf: [String: String] = [:]
        var versions: [String: [AssetEntryView]] = [:]
        for members in groups.values {
            let newest = members.sorted {
                ($0.createdAt ?? .distantPast) > ($1.createdAt ?? .distantPast)
            }
            let head = members.first { $0.id == graph.anchorEntryID }
                ?? members.first { !$0.isCandidate }
                ?? newest[0]
            versions[head.id] = [head] + newest.filter { $0.id != head.id }
            for member in members { headOf[member.id] = head.id }
        }
        return (headOf, versions)
    }

    /// 造型按派生深度排序（来源在前，同层保持接口顺序，默认造型在最前）。
    static func lookRows(_ graph: AssetGraphResponse) -> [LookRow] {
        let (headOf, _) = versionIndex(graph)
        let names = Dictionary(uniqueKeysWithValues: graph.variants.map { ($0.id, $0.name) })
        let order = graph.variants.map(\.id)
        var parents: [String: [AssetEdgeView]] = [:]
        for edge in graph.edges where edge.level == "variant" {
            parents[edge.targetID, default: []].append(edge)
        }
        var depth: [String: Int] = [:]
        func visit(_ id: String, _ trail: Set<String>) -> Int {
            if let known = depth[id] { return known }
            if trail.contains(id) { return 0 }
            let ups = parents[id] ?? []
            let value = ups.isEmpty ? 0 : (ups.map { visit($0.sourceID, trail.union([id])) }.max() ?? 0) + 1
            depth[id] = value
            return value
        }
        for id in order { _ = visit(id, []) }
        let sorted = order.enumerated().sorted {
            let (a, b) = (depth[$0.element] ?? 0, depth[$1.element] ?? 0)
            return a == b ? $0.offset < $1.offset : a < b
        }
        let byID = Dictionary(uniqueKeysWithValues: graph.variants.map { ($0.id, $0) })
        return sorted.compactMap { item -> LookRow? in
            guard let look = byID[item.element] else { return nil }
            return LookRow(
                look: look,
                depth: depth[look.id] ?? 0,
                parents: (parents[look.id] ?? []).map {
                    (names[$0.sourceID] ?? $0.sourceID, $0.relations, $0.label)
                },
                heads: look.entries.filter { headOf[$0.id] == $0.id }
            )
        }
    }

    /// 关系类型的显示名；自定义关系用它自己的名字。
    static func relationText(_ relations: [String], label: String?) -> String {
        relations.map { relation in
            relation == "custom" && label != nil ? label! : L10n.t("assetGraph.relation.\(relation)")
        }
        .joined(separator: " · ")
    }

    /// 造型 / 变体的「类属性」行：年龄 / 时代 / 场景光线·天气·状态 / 道具成色 / 服装 / 状态 / 场景 / 自定义。
    static func attributeRows(_ look: AssetVariantView) -> [(label: String, value: String)] {
        var rows: [(String, String)] = []
        if let age = look.presets["age_stage"] {
            rows.append((L10n.t("assetGraph.row.age_stage"), L10n.t("assetVariants.ageStage.\(age)")))
        }
        if let period = look.presets["period"] {
            rows.append((L10n.t("assetGraph.row.period"), L10n.t("remixPage.presets.period.\(period)")))
        }
        for (axis, label) in [("lighting", "axisLighting"), ("weather", "axisWeather"), ("state", "axisState")] {
            if let value = look.presets[axis] {
                rows.append((L10n.t("remixPage.presets.\(label)"), L10n.t("remixPage.presets.\(axis).\(value)")))
            }
        }
        if let condition = look.presets["prop_state"] {
            rows.append((L10n.t("props.stateLabel"), L10n.t("props.state.\(condition)")))
        }
        if let outfit = look.attributes?.outfit { rows.append((L10n.t("assetGraph.row.outfit"), outfit)) }
        if let state = look.attributes?.state { rows.append((L10n.t("assetGraph.row.state"), state)) }
        if let scene = look.sceneLink?.sceneName { rows.append((L10n.t("assetGraph.row.scene"), scene)) }
        if let note = look.attributes?.sceneNote { rows.append((L10n.t("assetGraph.row.scene_note"), note)) }
        for item in look.attributes?.custom ?? [] { rows.append((item.key, item.value)) }
        return rows
    }
}
