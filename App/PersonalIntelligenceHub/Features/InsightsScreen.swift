import SwiftUI

/// 「洞察」：合并原驾驶舱与情报中心。
///
/// - 概览：真实统计、趋势、来源分布与热点事件（原驾驶舱）。
/// - 情报报告：带引用的本地 AI 日报 / 周报（原情报中心）。
struct InsightsScreen: View {
    enum Tab: String, CaseIterable, Identifiable {
        case overview
        case reports

        var id: String { rawValue }
        var title: String {
            switch self {
            case .overview: return "概览"
            case .reports: return "情报报告"
            }
        }
    }

    @ObservedObject var model: SidecarViewModel
    @ObservedObject var personalization: PersonalizationStore
    let onOpenFeed: () -> Void
    let onOpenEvent: (String) -> Void
    let onOpenArticle: (String) -> Void

    @State private var tab: Tab = .overview

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: PIHSpacing.control) {
                PageHeader("洞察", subtitle: "趋势、排行与可追溯的本地情报报告")
                Spacer(minLength: 12)
                Picker("视图", selection: $tab) {
                    ForEach(Tab.allCases) { item in
                        Text(item.title).tag(item)
                    }
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                .frame(maxWidth: 280)
            }
            .padding(.horizontal, PIHSpacing.page)
            .padding(.vertical, 16)
            .background(PIHColor.canvas)

            Divider().overlay(PIHColor.hairline)

            switch tab {
            case .overview:
                DashboardScreen(
                    model: model,
                    personalization: personalization,
                    onOpenFeed: onOpenFeed
                )
            case .reports:
                IntelligenceScreen(
                    model: model,
                    onOpenEvent: onOpenEvent,
                    onOpenArticle: onOpenArticle
                )
            }
        }
    }
}
