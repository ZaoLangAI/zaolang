import ZaolangKit

/// `ZaolangKit.Operation`（文生视频/图生视频）与 `Foundation.Operation`（`NSOperation`）撞名；
/// 又因为 `ZaolangKit` 模块内还有一个同名的命名空间枚举 `ZaolangKit.ZaolangKit`，
/// 显式写 `ZaolangKit.Operation` 会被解析成"那个枚举里找不到的嵌套类型"而报错——
/// 唯一干净的办法是在一个不 `import Foundation` 的文件里先把裸 `Operation` 绑成本地别名，
/// 其余同时用到 `Foundation`（`Data`/`URL`/`UUID`…）的文件改用这个别名，不再写裸 `Operation`。
typealias GenerationOperation = Operation
