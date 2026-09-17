import Foundation

/// 从 `Localizable.xcstrings`（编译后就是标准的 strings 表）按 `namespace.key` 取文案，
/// 手工替换 `{var}` 占位符。为什么不用 Xcode 原生的位置参数机制，见
/// `ios/tools/gen-strings.py` 顶部注释——本机没有 Xcode 没法把那条链路跑一遍，
/// 这几行字符串替换反而是能靠读代码确认对不对的那种简单可靠。
enum L10n {
    /// - Parameters:
    ///   - key: 形如 `"discover.results"`。
    ///   - args: `{var}` 占位符对应的值，按名字替换；文案里没用到的 key 会被忽略。
    static func t(_ key: String, _ args: [String: CustomStringConvertible] = [:]) -> String {
        var value = Bundle.main.localizedString(forKey: key, value: key, table: "Localizable")
        for (name, arg) in args {
            value = value.replacingOccurrences(of: "{\(name)}", with: arg.description)
        }
        return value
    }
}
