import Foundation

/// Platform wall clock. Stored timestamps stay UTC; every screen converts here.
enum ZLClock {
    static let timeZone = TimeZone(identifier: "Asia/Shanghai")!

    static func dateTime(_ date: Date) -> String {
        var style = Date.FormatStyle(date: .abbreviated, time: .shortened)
        style.timeZone = timeZone
        return date.formatted(style)
    }

    static func time(_ date: Date) -> String {
        var style = Date.FormatStyle(date: .omitted, time: .standard)
        style.timeZone = timeZone
        return date.formatted(style)
    }

    static func date(_ date: Date) -> String {
        var style = Date.FormatStyle(date: .abbreviated, time: .omitted)
        style.timeZone = timeZone
        return date.formatted(style)
    }
}
