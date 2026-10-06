import Foundation
import ZaolangKit

/// The 创作 board's slot table and camera grid — a phone mirror of the web
/// workspace (`front/src/features/asset-workspace/kind-config.ts`, `camera.ts`,
/// `completeness.ts`, `slot-jobs.ts`); keep them in step. iOS reads every
/// slot (status, completeness, turnaround coverage) but fills only the
/// primary one — a character's 定妆照, a scene / prop variant's master; every
/// other slot continues on the web.
enum AssetSlots {
    enum Kind: Hashable {
        case portrait, sheet, pose, expressions, master, inScene, panorama
    }

    struct Slot: Identifiable, Hashable {
        let id: String
        let kind: Kind
        /// Counted by the completeness badge.
        let required: Bool
        var pose: CameraPose?

        /// The one slot iOS generates itself.
        var isPrimary: Bool { kind == .portrait || kind == .master }
    }

    enum Status: String {
        case missing, pending, candidate, approved
    }

    struct SlotState: Identifiable {
        let slot: Slot
        let status: Status
        let approved: AssetEntryView?
        let candidates: [AssetEntryView]

        var id: String { slot.id }
    }

    private static func poseSlot(_ id: String, _ pose: CameraPose, required: Bool = true) -> Slot {
        Slot(id: id, kind: .pose, required: required, pose: pose)
    }

    /// The standard set per card kind, in board order (web `KIND_CONFIG`).
    static func slots(_ kind: AssetCardKind) -> [Slot] {
        switch kind {
        case .character:
            [
                Slot(id: "portrait", kind: .portrait, required: true),
                Slot(id: "sheet", kind: .sheet, required: true),
                poseSlot("front_figure", CameraPose(azimuth: 0), required: false),
                poseSlot("side", CameraPose(azimuth: 90)),
                poseSlot("back", CameraPose(azimuth: 180)),
                poseSlot("left", CameraPose(azimuth: 270)),
                poseSlot("three_quarter", CameraPose(azimuth: 45)),
                Slot(id: "expressions", kind: .expressions, required: true),
                Slot(id: "in_scene", kind: .inScene, required: false),
            ]
        case .scene:
            [
                Slot(id: "master", kind: .master, required: true),
                poseSlot("reverse", CameraPose(azimuth: 180)),
                poseSlot("right", CameraPose(azimuth: 90)),
                poseSlot("left", CameraPose(azimuth: 270)),
                poseSlot("overhead", CameraPose(azimuth: 0, elevation: 60, distance: "wide")),
                poseSlot("detail", CameraPose(azimuth: 0, distance: "close"), required: false),
                Slot(id: "panorama", kind: .panorama, required: false),
            ]
        case .prop:
            [
                Slot(id: "master", kind: .master, required: true),
                poseSlot("side", CameraPose(azimuth: 90)),
                poseSlot("back", CameraPose(azimuth: 180)),
                poseSlot("left", CameraPose(azimuth: 270)),
                poseSlot("top", CameraPose(azimuth: 0, elevation: 60)),
                poseSlot("detail", CameraPose(azimuth: 0, distance: "close"), required: false),
            ]
        }
    }

    // MARK: - Camera grid (mirrors `app.domain.image_assets.camera`)

    static let azimuths = [0, 45, 90, 135, 180, 225, 270, 315]
    static let elevations = [-30, 0, 30, 60]
    static let distances = ["close", "medium", "wide"]

    private static func nearest(_ values: [Int], _ value: Int, wrap: Bool = false) -> Int {
        func gap(_ candidate: Int) -> Int {
            let raw = abs(candidate - value)
            return wrap ? min(raw, 360 - raw) : raw
        }
        return values.min { gap($0) < gap($1) } ?? values[0]
    }

    /// `pose` moved onto the grid.
    static func snap(_ pose: CameraPose) -> CameraPose {
        CameraPose(
            azimuth: nearest(azimuths, ((pose.azimuth % 360) + 360) % 360, wrap: true),
            elevation: nearest(elevations, pose.elevation),
            distance: distances.contains(pose.distance) ? pose.distance : "medium"
        )
    }

    /// `azimuth|elevation|distance` on the grid — one slot per key.
    static func poseKey(_ pose: CameraPose) -> String {
        let snapped = snap(pose)
        return "\(snapped.azimuth)|\(snapped.elevation)|\(snapped.distance)"
    }

    private static let viewPoses: [String: CameraPose] = [
        "front": CameraPose(azimuth: 0),
        "side": CameraPose(azimuth: 90),
        "back": CameraPose(azimuth: 180),
        "three_quarter": CameraPose(azimuth: 45),
        "reverse": CameraPose(azimuth: 180),
    ]

    /// The viewpoint an image shows — its stored `camera`, else what its
    /// coarse `view` stands for; a character sheet is the front.
    static func entryPose(_ entry: AssetEntryView) -> CameraPose? {
        if let camera = entry.camera { return camera }
        if entry.entryType == "character_sheet" { return CameraPose(azimuth: 0) }
        if entry.entryType == "view" || entry.entryType == "shot" {
            return entry.view.flatMap { viewPoses[$0] }
        }
        return nil
    }

    // MARK: - Completeness (mirrors `completeness.ts`)

    /// Which entries of a look / variant fill `slot` (any status). The
    /// identity portrait is card-wide — `allEntries` is every variant's.
    static func slotEntries(
        _ kind: AssetCardKind, _ slot: Slot, variant: AssetVariantView, allEntries: [AssetEntryView]
    ) -> [AssetEntryView] {
        let entries = variant.entries
        switch slot.kind {
        case .portrait: return allEntries.filter { $0.entryType == "identity_portrait" }
        case .sheet: return entries.filter { $0.entryType == "character_sheet" }
        case .expressions: return entries.filter { $0.entryType == "expression_sheet" }
        case .master: return entries.filter { $0.entryType == "master" }
        case .inScene: return entries.filter { $0.entryType == "pose" }
        case .panorama: return entries.filter { $0.entryType == "panorama" }
        case .pose:
            guard let wanted = slot.pose.map(poseKey) else { return [] }
            let type = kind == .scene ? "shot" : "view"
            return entries.filter { entry in
                guard entry.entryType == type, let shown = entryPose(entry) else { return false }
                return poseKey(shown) == wanted
            }
        }
    }

    /// A running job filing into this look that could produce `slot`: an
    /// orbit job for a pose slot, a panorama job for the panorama, any other
    /// job for the rest.
    private static func isPending(_ slot: Slot, variant: AssetVariantView, pending: [AssetGraphPendingJob]) -> Bool {
        pending.contains { job in
            guard job.targetVariantID == nil || job.targetVariantID == variant.id else { return false }
            switch slot.kind {
            case .pose: return job.mode == "orbit"
            case .panorama: return job.mode == "panorama"
            default: return job.mode != "orbit" && job.mode != "panorama"
            }
        }
    }

    static func slotStates(
        _ kind: AssetCardKind,
        variant: AssetVariantView,
        allEntries: [AssetEntryView],
        pending: [AssetGraphPendingJob] = []
    ) -> [SlotState] {
        slots(kind)
            .filter { $0.kind != .portrait || variant.isDefault }
            .map { slot in
                let matches = slotEntries(kind, slot, variant: variant, allEntries: allEntries)
                let approved = matches.first { !$0.isCandidate }
                let candidates = matches.filter(\.isCandidate)
                let status: Status = approved != nil
                    ? .approved
                    : isPending(slot, variant: variant, pending: pending)
                        ? .pending
                        : candidates.isEmpty ? .missing : .candidate
                return SlotState(slot: slot, status: status, approved: approved, candidates: candidates)
            }
    }

    /// `(done, total)` over the required slots — the library row badge.
    static func completeness(_ states: [SlotState]) -> (done: Int, total: Int) {
        let required = states.filter(\.slot.required)
        return (required.filter { $0.status == .approved }.count, required.count)
    }

    /// The default look / variant's completeness, from a list payload.
    static func cardCompleteness(_ kind: AssetCardKind, variants: [AssetVariantView]) -> (done: Int, total: Int)? {
        guard let main = variants.first(where: \.isDefault) ?? variants.first else { return nil }
        return completeness(slotStates(kind, variant: main, allEntries: variants.flatMap(\.entries)))
    }

    /// The turnaround ring: per azimuth at eye level, whether an approved or
    /// only a candidate image shows it. Medium and wide shots both count; a
    /// scene / prop master stands for 0°.
    static func coverage(_ kind: AssetCardKind, variant: AssetVariantView) -> [Int: Status] {
        let poseType = kind == .scene ? "shot" : "view"
        var map: [Int: Status] = [:]
        for entry in variant.entries {
            let pose: CameraPose?
            switch entry.entryType {
            case "master": pose = CameraPose(azimuth: 0)
            case poseType, "character_sheet": pose = entryPose(entry)
            default: pose = nil
            }
            guard let pose else { continue }
            let snapped = snap(pose)
            guard snapped.elevation == 0, snapped.distance != "close" else { continue }
            if !entry.isCandidate {
                map[snapped.azimuth] = .approved
            } else if map[snapped.azimuth] == nil {
                map[snapped.azimuth] = .candidate
            }
        }
        return map
    }

    // MARK: - Primary slot job (mirrors `slot-jobs.ts`)

    /// Card name, description and (a non-default look's) own description —
    /// the seed every slot job starts from.
    static func basePrompt(_ graph: AssetGraphResponse, variant: AssetVariantView) -> String {
        [graph.name, graph.description, variant.isDefault ? nil : variant.description]
            .map { part -> String in
                var text = (part ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
                while let last = text.last, last == "。" || last == "." { text.removeLast() }
                return text
            }
            .filter { !$0.isEmpty }
            .joined(separator: "。")
    }

    /// The draftless `POST /v1/generation-jobs` params that fill the primary
    /// slot of `variant`; `nil` for any other slot.
    static func primaryJobParams(
        _ kind: AssetCardKind, graph: AssetGraphResponse, variant: AssetVariantView, slot: Slot
    ) -> GenerationParams? {
        guard slot.isPrimary else { return nil }
        let prompt = basePrompt(graph, variant: variant)
        var params = GenerationParams(
            prompt: prompt.isEmpty ? graph.name : prompt,
            assetKind: kind.imageAssetKind,
            subjectNameHint: String(String.UnicodeScalarView(graph.name.unicodeScalars.prefix(60)))
        )
        switch kind {
        case .character: params.targetCharacterID = graph.cardID
        case .scene: params.targetSceneID = graph.cardID
        case .prop: params.targetPropID = graph.cardID
        }
        let presets = variant.presets
        switch (slot.kind, kind) {
        case (.portrait, _):
            params.characterPortrait = true
            params.aspectRatio = "3:4"
        case (.master, .scene):
            params.targetVariantID = variant.id
            params.aspectRatio = "16:9"
            params.sceneLighting = presets["lighting"]
            params.sceneWeather = presets["weather"]
            params.sceneState = presets["state"]
            params.scenePeriod = presets["period"]
        case (.master, _):
            params.targetVariantID = variant.id
            params.aspectRatio = "1:1"
            params.propState = presets["prop_state"]
        default:
            return nil
        }
        return params
    }

    // MARK: - Copy & links

    static func titleKey(_ kind: AssetCardKind) -> String {
        switch kind {
        case .character: "createPage.modeCharacterCreationTitle"
        case .scene: "createPage.modeSceneCreationTitle"
        case .prop: "createPage.modePropCreationTitle"
        }
    }

    static func newCardKey(_ kind: AssetCardKind) -> String {
        switch kind {
        case .character: "characters.newCharacter"
        case .scene: "scenes.newScene"
        case .prop: "props.newProp"
        }
    }

    /// The card's web workspace (`?look=` opens that look / variant), or the
    /// kind's library when `cardID` is `nil`.
    static func webURL(_ kind: AssetCardKind, cardID: String? = nil, variantID: String? = nil) -> URL? {
        var path = "\(AppConfig.webBaseURLString)/create/\(kind.segment)"
        if let cardID { path += "/\(cardID)" }
        guard var components = URLComponents(string: path) else { return nil }
        if cardID != nil, let variantID { components.queryItems = [URLQueryItem(name: "look", value: variantID)] }
        return components.url
    }
}
