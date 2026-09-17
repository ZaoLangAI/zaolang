import SwiftUI
import ZaolangKit

/// 横向 DAG 布局：按 `depth` 分列（负=上游，0=当前，正=下游），同列内按图里出现的顺序
/// 分行——上游是单链天然一行，下游有分支时才会在同列出现多行。双指缩放/拖动平移，
/// 双击复位，对应 `04-screens.md` 第 7 屏。
struct LineageCanvas: View {
    let graph: LineageGraph
    let selectedNodeID: String?
    let onSelect: (String) -> Void

    @Environment(\.zlMotion) private var reduceMotion
    private let columnSpacing: CGFloat = 132
    private let rowSpacing: CGFloat = 96

    @State private var scale: CGFloat = 1
    @State private var offset: CGSize = .zero
    @GestureState private var dragTranslation: CGSize = .zero
    @GestureState private var magnifyDelta: CGFloat = 1

    /// 显式写 init：`columnSpacing`/`rowSpacing` 是普通 `private let`（不是属性包裹器），
    /// 留给编译器合成逐一成员初始化器会把它的可见性降到 `private`，`LineageGraphView`
    /// 那个文件就调不到 `LineageCanvas(graph:...)` 了。
    init(graph: LineageGraph, selectedNodeID: String?, onSelect: @escaping (String) -> Void) {
        self.graph = graph
        self.selectedNodeID = selectedNodeID
        self.onSelect = onSelect
    }

    var body: some View {
        GeometryReader { proxy in
            let layout = Layout(graph: graph, columnSpacing: columnSpacing, rowSpacing: rowSpacing)
            ZStack {
                Canvas { context, _ in
                    for edge in graph.edges {
                        guard let from = layout.positions[edge.parentID], let to = layout.positions[edge.childID] else { continue }
                        var path = Path()
                        path.move(to: from)
                        path.addLine(to: to)
                        context.stroke(path, with: .color(Color.zl.border), lineWidth: 1.5)
                    }
                }

                ForEach(graph.nodes) { node in
                    if let position = layout.positions[node.id] {
                        LineageNodeView(node: node, isSelected: node.id == selectedNodeID)
                            .position(position)
                            .onTapGesture { onSelect(node.id) }
                            .accessibilityElement(children: .ignore)
                            .accessibilityLabel(node.title)
                            .accessibilityAddTraits(node.id == selectedNodeID ? [.isButton, .isSelected] : .isButton)
                            .accessibilityAction { onSelect(node.id) }
                    }
                }
            }
            .frame(width: layout.canvasSize.width, height: layout.canvasSize.height)
            .scaleEffect(scale * magnifyDelta)
            .offset(x: offset.width + dragTranslation.width, y: offset.height + dragTranslation.height)
            .position(x: proxy.size.width / 2, y: proxy.size.height / 2)
            .gesture(
                MagnificationGesture()
                    .updating($magnifyDelta) { value, state, _ in state = value }
                    .onEnded { value in scale = min(max(scale * value, 0.5), 3) }
            )
            .simultaneousGesture(
                DragGesture()
                    .updating($dragTranslation) { value, state, _ in state = value.translation }
                    .onEnded { value in
                        offset.width += value.translation.width
                        offset.height += value.translation.height
                    }
            )
            .onTapGesture(count: 2) {
                withAnimation(reduceMotion ? nil : .easeOut(duration: 0.2)) {
                    scale = 1
                    offset = .zero
                }
            }
        }
    }

    /// 只算一次列/行分配与像素坐标，`body` 每帧重跑也不重新分配——图结构不变的话结果稳定。
    private struct Layout {
        let positions: [String: CGPoint]
        let canvasSize: CGSize

        init(graph: LineageGraph, columnSpacing: CGFloat, rowSpacing: CGFloat) {
            var columns: [Int: [LineageGraph.Node]] = [:]
            for node in graph.nodes {
                columns[node.depth, default: []].append(node)
            }
            let depths = columns.keys.sorted()
            let minDepth = depths.first ?? 0
            let maxRowCount = columns.values.map(\.count).max() ?? 1

            var positions: [String: CGPoint] = [:]
            for depth in depths {
                guard let nodesInColumn = columns[depth] else { continue }
                let columnX = CGFloat(depth - minDepth) * columnSpacing + columnSpacing / 2
                let verticalOffset = CGFloat(maxRowCount - nodesInColumn.count) * rowSpacing / 2
                for (row, node) in nodesInColumn.enumerated() {
                    positions[node.id] = CGPoint(x: columnX, y: CGFloat(row) * rowSpacing + verticalOffset + rowSpacing / 2)
                }
            }

            self.positions = positions
            let width = CGFloat(depths.count) * columnSpacing + columnSpacing
            let height = CGFloat(maxRowCount) * rowSpacing + rowSpacing
            canvasSize = CGSize(width: max(width, 320), height: max(height, 240))
        }
    }
}

private struct LineageNodeView: View {
    let node: LineageGraph.Node
    let isSelected: Bool

    var body: some View {
        VStack(spacing: 6) {
            if node.isTombstone {
                Circle()
                    .strokeBorder(Color.zl.border, style: StrokeStyle(lineWidth: 1.5, dash: [4]))
                    .frame(width: 44, height: 44)
                    .overlay { Image(systemName: "xmark.seal").foregroundStyle(Color.zl.textMuted) }
            } else {
                RemoteImage(url: node.author?.avatarURL.flatMap(URL.init), aspectRatio: 1)
                    .frame(width: 44, height: 44)
                    .clipShape(Circle())
                    .overlay {
                        Circle().strokeBorder(node.isCurrent ? Color.zl.primary : (isSelected ? Color.zl.focus : .clear), lineWidth: node.isCurrent ? 3 : 2)
                    }
            }
            Text(node.title)
                .font(.system(size: 11))
                .lineLimit(1)
                .frame(width: 90)
                .foregroundStyle(Color.zl.text)
        }
    }
}
