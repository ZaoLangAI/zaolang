import Foundation

/// 创作链祖先节点（上游，数组形式，`depth` 从当前作品往上数）。
public struct LineageAncestor: Codable, Sendable, Equatable, Identifiable {
    public var id: String { workVersionID }
    public let workVersionID: String
    public let workID: String
    public let title: String
    public let author: AuthorSummary?
    public let depth: Int
    public let isTombstone: Bool
    public let coverURL: String?

    private enum CodingKeys: String, CodingKey {
        case workVersionID = "work_version_id"
        case workID = "work_id"
        case title, author, depth
        case isTombstone = "is_tombstone"
        case coverURL = "cover_url"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        workVersionID = try c.decode(String.self, forKey: .workVersionID)
        workID = try c.decode(String.self, forKey: .workID)
        title = try c.decode(String.self, forKey: .title)
        author = try c.decodeIfPresent(AuthorSummary.self, forKey: .author)
        depth = try c.decode(Int.self, forKey: .depth)
        isTombstone = try c.decodeIfPresent(Bool.self, forKey: .isTombstone) ?? false
        coverURL = try c.decodeIfPresent(String.self, forKey: .coverURL)
    }
}

/// 创作链下游节点，后端给的是**递归树**而不是边列表：`root` 是当前作品，`children` 逐层往下。
///
/// `author` 在 OpenAPI 里是自由 object（没有 `$ref` 到 `AuthorSummary`），这里按同样的字段形状
/// 宽松解析：缺字段就整体降级为 `nil`，绝不因为这一个自由字段让整棵树解码失败。
public struct LineageNodeResponse: Codable, Sendable, Equatable, Identifiable {
    public var id: String { workVersionID }
    public let workVersionID: String
    public let workID: String
    public let title: String
    public let author: AuthorSummary?
    public let depth: Int
    public let isTombstone: Bool
    public let coverURL: String?
    public let children: [LineageNodeResponse]

    private enum CodingKeys: String, CodingKey {
        case workVersionID = "work_version_id"
        case workID = "work_id"
        case title, author, depth
        case isTombstone = "is_tombstone"
        case coverURL = "cover_url"
        case children
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        workVersionID = try c.decode(String.self, forKey: .workVersionID)
        workID = try c.decode(String.self, forKey: .workID)
        title = try c.decode(String.self, forKey: .title)
        author = try? c.decode(AuthorSummary.self, forKey: .author) // 自由 object，解不出就是 nil
        depth = try c.decode(Int.self, forKey: .depth)
        isTombstone = try c.decode(Bool.self, forKey: .isTombstone)
        coverURL = try c.decodeIfPresent(String.self, forKey: .coverURL)
        children = try c.decodeIfPresent([LineageNodeResponse].self, forKey: .children) ?? []
    }
}

/// `GET /v1/works/{id}/lineage` 的完整响应：上游 `ancestors` 数组 + 下游 `root` 递归树。
/// 两个方向合在一次请求里，图谱只用一次网络往返就能画出来。
public struct LineageResponse: Codable, Sendable, Equatable {
    public let root: LineageNodeResponse
    public let ancestors: [LineageAncestor]
    public let totalDescendants: Int
    public let truncated: Bool

    private enum CodingKeys: String, CodingKey {
        case root, ancestors
        case totalDescendants = "total_descendants"
        case truncated
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        root = try c.decode(LineageNodeResponse.self, forKey: .root)
        ancestors = try c.decodeIfPresent([LineageAncestor].self, forKey: .ancestors) ?? []
        totalDescendants = try c.decodeIfPresent(Int.self, forKey: .totalDescendants) ?? 0
        truncated = try c.decodeIfPresent(Bool.self, forKey: .truncated) ?? false
    }
}

/// 选中节点与父版本的参数差异。`parentValue` / `childValue` 后端不声明类型，用 `JSONValue` 兜底。
public struct VersionDiffEntry: Codable, Sendable, Equatable {
    public let field: String
    public let parentValue: JSONValue?
    public let childValue: JSONValue?
    public let changed: Bool

    private enum CodingKeys: String, CodingKey {
        case field
        case parentValue = "parent_value"
        case childValue = "child_value"
        case changed
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        field = try c.decode(String.self, forKey: .field)
        parentValue = try c.decodeIfPresent(JSONValue.self, forKey: .parentValue)
        childValue = try c.decodeIfPresent(JSONValue.self, forKey: .childValue)
        changed = try c.decodeIfPresent(Bool.self, forKey: .changed) ?? false
    }
}

public struct VersionDiffResponse: Codable, Sendable, Equatable {
    public let parentWorkVersionID: String
    public let childWorkVersionID: String
    public let entries: [VersionDiffEntry]

    private enum CodingKeys: String, CodingKey {
        case parentWorkVersionID = "parent_work_version_id"
        case childWorkVersionID = "child_work_version_id"
        case entries
    }
}

/// 创作链图谱渲染前，把 `ancestors` 数组 + `root` 递归树拼成的统一节点/边模型。
/// 布局代码只认这一个模型，不用同时关心两种后端形状。
public struct LineageGraph: Sendable {
    public struct Node: Sendable, Identifiable, Equatable {
        public let id: String // workVersionID
        public let workID: String
        public let title: String
        public let author: AuthorSummary?
        public let coverURL: String?
        public let depth: Int // 负数=上游，0=当前作品，正数=下游
        public let isTombstone: Bool
        public let isCurrent: Bool
    }

    public struct Edge: Sendable, Identifiable, Equatable {
        public var id: String { "\(parentID)->\(childID)" }
        public let parentID: String
        public let childID: String
    }

    public let nodes: [Node]
    public let edges: [Edge]
    public let currentNodeID: String
    public let truncated: Bool
    public let totalDescendants: Int

    /// 从 `LineageResponse` 构建统一图模型：祖先链按 depth 升序接到 root 之前，
    /// root 的递归 `children` 展开成正深度的边。
    public init(response: LineageResponse) {
        var nodes: [Node] = []
        var edges: [Edge] = []

        let sortedAncestors = response.ancestors.sorted { $0.depth > $1.depth } // 离当前作品最远的在前
        for (index, ancestor) in sortedAncestors.enumerated() {
            nodes.append(
                Node(
                    id: ancestor.workVersionID,
                    workID: ancestor.workID,
                    title: ancestor.title,
                    author: ancestor.author,
                    coverURL: ancestor.coverURL,
                    depth: -(sortedAncestors.count - index),
                    isTombstone: ancestor.isTombstone,
                    isCurrent: false
                )
            )
        }
        for i in 0..<sortedAncestors.count where i + 1 < sortedAncestors.count {
            edges.append(Edge(parentID: sortedAncestors[i].workVersionID, childID: sortedAncestors[i + 1].workVersionID))
        }
        if let lastAncestor = sortedAncestors.last {
            edges.append(Edge(parentID: lastAncestor.workVersionID, childID: response.root.workVersionID))
        }

        func walk(_ node: LineageNodeResponse, isRoot: Bool) {
            nodes.append(
                Node(
                    id: node.workVersionID,
                    workID: node.workID,
                    title: node.title,
                    author: node.author,
                    coverURL: node.coverURL,
                    depth: node.depth,
                    isTombstone: node.isTombstone,
                    isCurrent: isRoot
                )
            )
            for child in node.children {
                edges.append(Edge(parentID: node.workVersionID, childID: child.workVersionID))
                walk(child, isRoot: false)
            }
        }
        walk(response.root, isRoot: true)

        self.nodes = nodes
        self.edges = edges
        self.currentNodeID = response.root.workVersionID
        self.truncated = response.truncated
        self.totalDescendants = response.totalDescendants
    }
}
