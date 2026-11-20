// Phase 6.1 Intelligent cockpit (Dashboard).
// Phase 7.0: unified design system, larger typography, calmer layout.
// Pure SwiftUI. All data from /api/v1/dashboard. No charting libs.

import SwiftUI

// MARK: - DTOs

private struct DashboardOverview: Decodable {
    struct Articles: Decodable { let total, today, last7Days, unread, favorites: Int }
    struct Sources: Decodable { let total, active: Int }
    struct Events: Decodable { let total, active: Int }

    let generatedAt: String
    let articles: Articles
    let sources: Sources
    let events: Events
}

private struct DashboardTrendPoint: Decodable {
    let day: String
    let count: Int
}

private struct DashboardTrendResponse: Decodable {
    let days: Int
    let items: [DashboardTrendPoint]
}

private struct DashboardTopItem: Decodable, Identifiable {
    let name: String
    let articlesCount: Int
    let category: String?
    let language: String?
    let lastFetched: String?

    var id: String { name }
}

private struct DashboardCategoryItem: Decodable, Identifiable {
    let name: String
    let articlesCount: Int

    var id: String { name }
}

private struct DashboardEventItem: Decodable, Identifiable {
    let id: String
    let title: String
    let summary: String?
    let heatScore: Double
    let importanceScore: Double
    let status: String
    let firstSeenAt: String?
    let lastSeenAt: String?
    let articleCount: Int
}

// MARK: - Store

@MainActor
private final class DashboardStore: ObservableObject {
    var client: APIClient
    @Published var overview: DashboardOverview?
    @Published var trend: [DashboardTrendPoint] = []
    @Published var sourcesTop: [DashboardTopItem] = []
    @Published var categories: [DashboardCategoryItem] = []
    @Published var events: [DashboardEventItem] = []
    @Published var loading = false
    @Published var error: String?

    init(client: APIClient) { self.client = client }

    func load() async {
        loading = true
        error = nil
        defer { loading = false }
        do {
            overview = try await client.perform("GET", path: "/api/v1/dashboard/overview", as: DashboardOverview.self)
            trend = try await client.perform(
                "GET",
                path: "/api/v1/dashboard/articles/trend",
                query: [URLQueryItem(name: "days", value: "14")],
                as: DashboardTrendResponse.self
            ).items
            sourcesTop = try await client.perform("GET", path: "/api/v1/dashboard/sources", as: [String:[DashboardTopItem]].self)["items"] ?? []
            categories = try await client.perform("GET", path: "/api/v1/dashboard/categories", as: [String:[DashboardCategoryItem]].self)["items"] ?? []
            events = try await client.perform(
                "GET",
                path: "/api/v1/dashboard/events/hot",
                query: [URLQueryItem(name: "limit", value: "5")],
                as: [String: [DashboardEventItem]].self
            )["items"] ?? []
        } catch {
            self.error = "\(error)"
        }
    }
}

// MARK: - Root

struct DashboardScreen: View {
    @ObservedObject var model: SidecarViewModel
    @ObservedObject var personalization: PersonalizationStore
    var onOpenFeed: () -> Void
    @State private var store: DashboardStore?

    var body: some View {
        Group {
            if !model.isDataReady {
                EmptyPanel(
                    icon: "bolt.horizontal.circle",
                    title: "本地服务未就绪",
                    message: "驾驶舱需要本地 Sidecar 运行。当前状态：\(model.state.title)。",
                    actionTitle: "启动 Sidecar",
                    action: { model.start() }
                )
            } else if let store {
                DashboardContentView(store: store, personalization: personalization, onOpenFeed: onOpenFeed)
            } else {
                LoadingStateView(message: "正在连接本地驾驶舱…")
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(PIHColor.canvas)
        // 首帧可能早于 Sidecar 握手完成，此时 apiClient 尚未就绪；
        // 用 task(id:) 跟随 state 变化，握手成功后自动补拉数据，避免永久停留加载态。
        .task(id: model.state) {
            guard model.isDataReady, let client = model.apiClientForFeatures else { return }
            if let store {
                store.client = client
                if store.overview == nil {
                    await store.load()
                }
            } else {
                let s = DashboardStore(client: client)
                store = s
                await s.load()
            }
            await personalization.loadIfNeeded()
        }
    }
}

// MARK: - Content

private struct DashboardContentView: View {
    @ObservedObject var store: DashboardStore
    @ObservedObject var personalization: PersonalizationStore
    var onOpenFeed: () -> Void

    private let cardColumns = [GridItem(.adaptive(minimum: 430), spacing: PIHSpacing.cardGap)]
    private let metricColumns = [GridItem(.adaptive(minimum: 200), spacing: PIHSpacing.cardGap)]

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: PIHSpacing.section) {
                header
                if store.loading && store.overview == nil {
                    LoadingStateView(message: "正在读取驾驶舱数据…")
                        .frame(height: 320)
                } else if let error = store.error {
                    ErrorBanner(
                        message: error,
                        requestID: nil,
                        onRetry: { Task { await store.load() } },
                        onDismiss: { store.error = nil }
                    )
                } else {
                    overviewCards
                    personalSummary
                    LazyVGrid(columns: cardColumns, alignment: .leading, spacing: PIHSpacing.cardGap) {
                        trendCard
                        sourcesCard
                        categoriesCard
                        eventsCard
                    }
                }
            }
            .padding(.horizontal, PIHSpacing.page)
            .padding(.vertical, PIHSpacing.section)
        }
    }

    private var header: some View {
        PageHeader("智能驾驶舱", subtitle: "今天的情报概览 · 数据来自本地采集与分析") {
            HStack(spacing: PIHSpacing.control) {
                if let t = store.overview?.generatedAt {
                    Text("更新于 \(PIHDateFormat.display(t))")
                        .font(PIHFont.meta)
                        .foregroundStyle(.secondary)
                }
                Button {
                    Task { await store.load() }
                } label: {
                    Label("刷新", systemImage: "arrow.clockwise")
                        .font(PIHFont.caption)
                }
                .disabled(store.loading)
                .help("刷新驾驶舱数据")
            }
        }
    }

    // MARK: - Metric cards

    private var overviewCards: some View {
        let o = store.overview
        return LazyVGrid(columns: metricColumns, alignment: .leading, spacing: PIHSpacing.cardGap) {
            MetricCard(
                title: "文章总数",
                value: "\(o?.articles.total ?? 0)",
                subtitle: "今日发布 \(o?.articles.today ?? 0) · 近 7 天 \(o?.articles.last7Days ?? 0)",
                icon: "newspaper",
                tint: .accentColor
            )
            MetricCard(
                title: "未读文章",
                value: "\(o?.articles.unread ?? 0)",
                subtitle: "收藏 \(o?.articles.favorites ?? 0)",
                icon: "envelope.badge",
                tint: .orange
            )
            MetricCard(
                title: "信息源",
                value: "\(o?.sources.total ?? 0)",
                subtitle: "活跃 \(o?.sources.active ?? 0)",
                icon: "dot.radiowaves.left.and.right",
                tint: .blue
            )
            MetricCard(
                title: "事件",
                value: "\(o?.events.total ?? 0)",
                subtitle: "活跃 \(o?.events.active ?? 0)",
                icon: "rectangle.3.group",
                tint: .purple
            )
        }
    }

    // MARK: - Personal feed summary (Phase 7.3.1)

    @ViewBuilder
    private var personalSummary: some View {
        if let stats = personalization.stats {
            PIHCard {
                CardHeader("为我筛选", icon: "wand.and.stars") {
                    Button("打开", action: onOpenFeed)
                        .controlSize(.small)
                }
                HStack(spacing: 18) {
                    summaryMetric("今日推荐", "\(stats.recommendations.total)", "条当前推荐")
                    summaryMetric("必读", "\(stats.recommendations.byLevel["must_read"] ?? 0)", "85 分以上")
                    summaryMetric("核心兴趣", "\(stats.interests.byLevel["core"] ?? 0)", "个核心关注")
                    summaryMetric("今日新增", "\(stats.today.articles)", "篇文章 · \(stats.today.events) 个事件")
                    Spacer(minLength: 0)
                }
            }
        }
    }

    private func summaryMetric(_ title: String, _ value: String, _ caption: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title)
                .font(PIHFont.meta)
                .foregroundStyle(.secondary)
            Text(value)
                .font(.system(size: 20, weight: .semibold))
                .monospacedDigit()
            Text(caption)
                .font(PIHFont.meta)
                .foregroundStyle(.tertiary)
        }
    }

    // MARK: - Trend chart

    private var trendCard: some View {
        PIHCard {
            CardHeader("近 14 天文章趋势", icon: "chart.line.uptrend.xyaxis") {
                Text("\(store.trend.reduce(0) { $0 + $1.count }) 篇")
                    .font(PIHFont.meta)
                    .foregroundStyle(.secondary)
            }
            if store.trend.isEmpty {
                empty("暂无趋势数据。完成一次采集后会显示每日文章数量。")
            } else {
                BarChart(points: store.trend.map { ($0.day, Double($0.count)) })
                    .frame(height: 190)
                    .padding(.top, 4)
                Text("按文章发布时间统计，缺失时回退采集时间（UTC）；零值日期同样显示。")
                    .font(PIHFont.meta)
                    .foregroundStyle(.tertiary)
            }
        }
    }

    // MARK: - Sources

    private var sourcesCard: some View {
        PIHCard {
            CardHeader("信息源 Top 10", icon: "dot.radiowaves.forward") {
                Text("按文章数")
                    .font(PIHFont.meta)
                    .foregroundStyle(.secondary)
            }
            let top = Array(store.sourcesTop.prefix(10))
            if top.isEmpty {
                empty("暂无信息源文章。请先在「信息源」中添加并采集。")
            } else {
                VStack(spacing: 10) {
                    ForEach(top) { item in
                        HStack(spacing: 10) {
                            Text(item.name)
                                .font(PIHFont.caption)
                                .lineLimit(1)
                                .frame(width: 128, alignment: .leading)
                            GeometryReader { geo in
                                let maxVal = top.map(\.articlesCount).max() ?? 1
                                let w = max(3, geo.size.width * Double(item.articlesCount) / Double(maxVal))
                                RoundedRectangle(cornerRadius: 4, style: .continuous)
                                    .fill(Color.accentColor.opacity(0.65))
                                    .frame(width: w)
                            }
                            .frame(height: 8)
                            Text("\(item.articlesCount)")
                                .font(PIHFont.meta)
                                .monospacedDigit()
                                .foregroundStyle(.secondary)
                                .frame(width: 36, alignment: .trailing)
                        }
                    }
                }
            }
        }
    }

    // MARK: - Categories

    private var categoriesCard: some View {
        PIHCard {
            CardHeader("领域分布", icon: "chart.pie") {
                Text("\(store.categories.count) 个分类")
                    .font(PIHFont.meta)
                    .foregroundStyle(.secondary)
            }
            if store.categories.isEmpty {
                empty("暂无分类数据。")
            } else {
                HStack(alignment: .top, spacing: 20) {
                    CategoryDonut(items: store.categories)
                        .frame(width: 148, height: 148)
                    VStack(alignment: .leading, spacing: 9) {
                        ForEach(Array(store.categories.enumerated()), id: \.element.id) { index, item in
                            HStack(spacing: 8) {
                                Circle()
                                    .fill(CategoryDonut.palette[index % CategoryDonut.palette.count])
                                    .frame(width: 8, height: 8)
                                Text(item.name)
                                    .font(PIHFont.caption)
                                    .lineLimit(1)
                                Spacer(minLength: 8)
                                Text("\(item.articlesCount)")
                                    .font(PIHFont.meta)
                                    .monospacedDigit()
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
        }
        .fixedSize(horizontal: false, vertical: true)
    }

    // MARK: - Hot events

    private var eventsCard: some View {
        PIHCard {
            CardHeader("热点事件", icon: "flame.fill") {
                if !store.events.isEmpty {
                    Text("前 \(store.events.count) 个")
                        .font(PIHFont.meta)
                        .foregroundStyle(.secondary)
                }
            }
            if store.events.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    Text("尚未生成热点事件")
                        .font(PIHFont.bodyMedium)
                    Text("事件由本地聚类生成。可在「事件中心」运行一次增量聚类，结果会出现在这里。")
                        .font(PIHFont.caption)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(.vertical, 6)
            } else {
                VStack(spacing: 0) {
                    ForEach(Array(store.events.enumerated()), id: \.element.id) { index, ev in
                        HStack(alignment: .top, spacing: 12) {
                            Text("\(index + 1)")
                                .font(PIHFont.meta.weight(.semibold))
                                .foregroundStyle(.tertiary)
                                .frame(width: 16, alignment: .trailing)
                                .padding(.top, 2)
                            VStack(alignment: .leading, spacing: 5) {
                                Text(ev.title)
                                    .font(PIHFont.bodyMedium)
                                    .lineLimit(2)
                                    .fixedSize(horizontal: false, vertical: true)
                                HStack(spacing: 8) {
                                    Label(String(format: "热度 %.1f", ev.heatScore), systemImage: "flame")
                                        .foregroundStyle(.orange)
                                    Text("\(ev.articleCount) 篇")
                                    Text(eventStatusText(ev.status))
                                }
                                .font(PIHFont.meta)
                                .foregroundStyle(.secondary)
                            }
                            Spacer(minLength: 0)
                        }
                        .padding(.vertical, 10)
                        if index < store.events.count - 1 {
                            Divider().overlay(PIHColor.hairline)
                        }
                    }
                }
            }
        }
    }

    private func eventStatusText(_ raw: String) -> String {
        switch raw {
        case "active": return "活跃"
        case "evolving": return "发展中"
        case "dormant": return "休眠"
        case "closed": return "已结束"
        case "merged": return "已合并"
        case "candidate": return "候选"
        case "archived": return "已归档"
        default: return raw
        }
    }

    private func empty(_ text: String) -> some View {
        Text(text)
            .font(PIHFont.caption)
            .foregroundStyle(.secondary)
            .frame(maxWidth: .infinity, minHeight: 120, alignment: .center)
            .multilineTextAlignment(.center)
    }
}

// MARK: - Simple bar chart (no lib)

private struct BarChart: View {
    let points: [(String, Double)]

    var body: some View {
        let maxVal = points.map { $0.1 }.max() ?? 1
        let count = points.count
        GeometryReader { geo in
            let spacing: CGFloat = 6
            let available = max(0, geo.size.width - spacing * CGFloat(max(count - 1, 0)))
            let barWidth = min(44, max(8, available / CGFloat(max(count, 1))))
            let chartHeight = max(12, geo.size.height - 38)
            HStack(alignment: .bottom, spacing: spacing) {
                if count < 7 { Spacer(minLength: 0) }
                ForEach(Array(points.enumerated()), id: \.offset) { idx, p in
                    VStack(spacing: 5) {
                        if p.1 > 0 {
                            Text(String(Int(p.1)))
                                .font(.system(size: 10))
                                .foregroundStyle(.secondary)
                                .monospacedDigit()
                                .lineLimit(1)
                                .fixedSize()
                        } else {
                            Text(" ")
                                .font(.system(size: 10))
                        }
                        RoundedRectangle(cornerRadius: 4, style: .continuous)
                            .fill(
                                p.1 > 0
                                ? AnyShapeStyle(LinearGradient(
                                    colors: [Color.accentColor.opacity(0.85), Color.accentColor.opacity(0.45)],
                                    startPoint: .top,
                                    endPoint: .bottom
                                ))
                                : AnyShapeStyle(Color.secondary.opacity(0.14))
                            )
                            .frame(height: max(3, chartHeight * p.1 / max(maxVal, 1)))
                            .help("\(p.0)：\(Int(p.1)) 篇")
                        if idx % max(1, count / 7) == 0 || idx == count - 1 {
                            Text(String(p.0.suffix(5)))
                                .font(.system(size: 10))
                                .foregroundStyle(.tertiary)
                                .lineLimit(1)
                        } else {
                            Text(" ").font(.system(size: 10))
                        }
                    }
                    .frame(width: barWidth)
                }
                if count < 7 { Spacer(minLength: 0) }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

// MARK: - Donut (categories)

private struct CategoryDonut: View {
    static let palette: [Color] = [
        .accentColor, .orange, .green, .purple, .pink, .cyan, .red, .indigo
    ]

    let items: [DashboardCategoryItem]

    private struct SliceData: Identifiable {
        let id: Int
        let start: CGFloat
        let end: CGFloat
        let color: Color
    }

    var body: some View {
        let total = items.reduce(0) { $0 + $1.articlesCount }
        var cursor: CGFloat = 0
        let slices: [SliceData] = items.enumerated().map { idx, item in
            let fraction = CGFloat(item.articlesCount) / CGFloat(max(total, 1))
            let slice = SliceData(
                id: idx,
                start: cursor,
                end: cursor + fraction,
                color: Self.palette[idx % Self.palette.count]
            )
            cursor += fraction
            return slice
        }
        return ZStack {
            Circle()
                .stroke(Color.secondary.opacity(0.12), lineWidth: 16)
            ForEach(slices) { slice in
                Circle()
                    .trim(from: slice.start, to: max(slice.start, slice.end - 0.002))
                    .stroke(slice.color, style: StrokeStyle(lineWidth: 16, lineCap: .butt))
                    .rotationEffect(.degrees(-90))
            }
            VStack(spacing: 1) {
                Text("\(total)")
                    .font(.system(size: 22, weight: .bold, design: .rounded))
                    .monospacedDigit()
                Text("篇文章")
                    .font(PIHFont.meta)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(10)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("领域分布共 \(total) 篇文章")
    }
}
