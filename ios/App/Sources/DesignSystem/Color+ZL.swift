import SwiftUI

/// 网页端 `globals.css` 的语义色板在这里对应一份。命名与 `ios/tools/gen-colors.py`
/// 生成的 Asset Catalog 名字一一对应，色值本身**不在这里，也不在任何 Swift 源码里**，
/// 只有一处真源：`Assets.xcassets/Colors/*.colorset`（由脚本从网页端 CSS 变量生成）。
///
/// 组件代码只准用 `Color.zl.*`，不准在视图里直接写字面量色值——这是网页端同一条规则
/// 在 iOS 上的对应版本（见 `front/src/app/globals.css` 顶部注释）。
extension Color {
    struct ZLPalette {
        let bg = Color("Bg")
        let surface = Color("Surface")
        let surfaceRaised = Color("SurfaceRaised")
        let surfaceSoft = Color("SurfaceSoft")
        let text = Color("Text")
        let textMuted = Color("TextMuted")
        let border = Color("Border")
        let primary = Color("Primary")
        let primaryHover = Color("PrimaryHover")
        let onPrimary = Color("OnPrimary")
        let amber = Color("Amber")
        let success = Color("Success")
        let danger = Color("Danger")
        let focus = Color("Focus")
        let posterTint = Color("PosterTint")
        let overlay = Color("Overlay")
        let skeleton = Color("Skeleton")
        let track = Color("Track")
        // 角色管理图的关系类型色（`--relation-*`）。
        let relationAge = Color("RelationAge")
        let relationOutfit = Color("RelationOutfit")
        let relationEmotion = Color("RelationEmotion")
        let relationScene = Color("RelationScene")
        let relationPeriod = Color("RelationPeriod")
        let relationEdit = Color("RelationEdit")
        let relationCustom = Color("RelationCustom")

        /// 与网页 `asset-graph/relations.ts` 的 `RELATION_COLOR` 同一映射。
        func relation(_ relation: String) -> Color {
            switch relation {
            case "age", "lighting": relationAge
            case "outfit": relationOutfit
            case "emotion", "state": relationEmotion
            case "scene", "weather": relationScene
            case "period", "params": relationPeriod
            case "edit": relationEdit
            default: relationCustom
            }
        }
    }

    static let zl = ZLPalette()
}
