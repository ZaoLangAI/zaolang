import Foundation
import ZaolangKit

/// 三语标签（`TagResponse.label(for:)`）要按 App 当前界面语言选，不是账号偏好——
/// 游客没有 `me.locale`，界面语言完全由系统 / App 本地化决定，跟 `L10n` 走的是同一套。
enum CurrentAppLocale {
    static var value: AppLocale {
        let preferred = Bundle.main.preferredLocalizations.first ?? "zh-Hans"
        if preferred.hasPrefix("en") { return .en }
        if preferred.hasPrefix("ja") { return .ja }
        return .zhCN
    }

    /// 只是注册表单的初始选中项，不是强制绑定——地区只管定价货币，界面语言不联动它，
    /// 用户在设置里随时能改（见 `zaolang-i18n-region` 的地区/语言解耦规则）。
    static var suggestedRegion: Region {
        switch value {
        case .zhCN: .cn
        case .ja: .jp
        case .en: .global
        }
    }
}
