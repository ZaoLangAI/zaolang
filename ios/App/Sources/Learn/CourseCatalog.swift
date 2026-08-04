import Foundation

/// 对应 Web 端 `(site)/learn/page.tsx` 里硬编码的 `COURSES` 常量。课程内容本地静态，
/// 不建后端端点（`ios_m0_m1` 计划"不做的事"一节），三门课固定，不需要动态扩展。
struct CourseInfo: Identifiable {
    let index: Int
    let levelKey: String
    let titleKey: String
    let descKey: String
    let seconds: Int

    var id: Int { index }
}

enum CourseCatalog {
    static let courses: [CourseInfo] = [
        CourseInfo(index: 1, levelKey: "learnPage.levelBeginner", titleKey: "learnPage.course1Title", descKey: "learnPage.course1Desc", seconds: 320),
        CourseInfo(index: 2, levelKey: "learnPage.levelIntermediate", titleKey: "learnPage.course2Title", descKey: "learnPage.course2Desc", seconds: 525),
        CourseInfo(index: 3, levelKey: "learnPage.levelRequired", titleKey: "learnPage.course3Title", descKey: "learnPage.course3Desc", seconds: 370),
    ]

    static func course(at index: Int) -> CourseInfo? {
        courses.first { $0.index == index }
    }
}
