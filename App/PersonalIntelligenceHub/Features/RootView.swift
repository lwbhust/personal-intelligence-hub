import SwiftUI

/// 五个一级入口：今日 / 阅读 / 事件 / 洞察 / 设置。
///
/// 工程页（AI 分析、自动化管道、采集任务、运行状态、分类）不再是一级导航，
/// 统一收敛到「设置 → 高级诊断」，能力保留、日常折叠。
enum AppSection: String, CaseIterable, Identifiable {
    case today
    case reading
    case events
    case insights
    case settings

    var id: String { rawValue }

    var title: String {
        switch self {
        case .today: return "今日"
        case .reading: return "阅读"
        case .events: return "事件"
        case .insights: return "洞察"
        case .settings: return "设置"
        }
    }

    var icon: String {
        switch self {
        case .today: return "sun.max"
        case .reading: return "book"
        case .events: return "rectangle.3.group"
        case .insights: return "chart.bar.xaxis"
        case .settings: return "gearshape"
        }
    }

    static let daily: [AppSection] = [.today, .reading, .events, .insights]
}

struct RootView: View {
    @ObservedObject var model: SidecarViewModel
    @StateObject private var store = SourcesStore()
    @StateObject private var articlesStore = ArticlesStore()
    @StateObject private var jobsStore = CollectionJobsStore()
    @StateObject private var aiStore = AIStore()
    @StateObject private var eventStore = EventStore()
    @StateObject private var pipelineStore = PipelineStore()
    @StateObject private var personalizationStore = PersonalizationStore()
    @StateObject private var todayStore = TodayStore()
    @State private var section: AppSection? = .today

    var body: some View {
        NavigationSplitView {
            sidebar
                .navigationSplitViewColumnWidth(min: 208, ideal: 234, max: 280)
        } detail: {
            detail
        }
        .navigationSplitViewStyle(.balanced)
        .task { model.autoStartIfNeeded() }
        .task(id: model.state) {
            let client = model.apiClientForFeatures
            store.bind(client)
            articlesStore.bind(client)
            jobsStore.bind(client)
            aiStore.bind(client)
            eventStore.bind(client)
            pipelineStore.bind(client)
            personalizationStore.bind(client)
            todayStore.bind(client)
        }
    }

    // MARK: - Sidebar

    private var sidebar: some View {
        List(selection: $section) {
            brandHeader
                .listRowInsets(EdgeInsets(top: 14, leading: 14, bottom: 8, trailing: 14))
                .listRowBackground(Color.clear)

            Section {
                ForEach(AppSection.daily) { row($0) }
            }

            Section {
                row(.settings)
            }
        }
        .listStyle(.sidebar)
        .safeAreaInset(edge: .bottom) {
            sidecarFooter
        }
    }

    private var brandHeader: some View {
        HStack(spacing: 10) {
            Image(systemName: "brain.head.profile")
                .font(PIHFont.cardTitle)
                .foregroundStyle(.tint)
                .frame(width: 32, height: 32)
                .background(
                    RoundedRectangle(cornerRadius: 9, style: .continuous)
                        .fill(PIHColor.accentSoft)
                )
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 0) {
                Text("PIH")
                    .font(PIHFont.sideBarSectionTitle)
                    .foregroundStyle(.primary)
                    .lineLimit(1)
                Text("Personal Intelligence Hub")
                    .font(PIHFont.sideBarSubtitle.weight(.medium))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .minimumScaleFactor(0.65)
            }
            Spacer(minLength: 0)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Personal Intelligence Hub，个人智能情报中枢")
    }

    private func row(_ item: AppSection) -> some View {
        Label {
            Text(item.title)
                .font(PIHFont.sideBarLabel)
                .foregroundStyle(.primary)
        } icon: {
            Image(systemName: item.icon)
                .font(PIHFont.sideBarLabelRegular)
                .frame(width: 20, alignment: .center)
        }
        .padding(.vertical, 6)
        .tag(item)
        .accessibilityLabel(item.title)
    }

    private var sidecarFooter: some View {
        VStack(spacing: 0) {
            Divider()
            Button {
                section = .settings
            } label: {
                HStack(spacing: 8) {
                    Circle()
                        .fill(model.state.tint)
                        .frame(width: 8, height: 8)
                    VStack(alignment: .leading, spacing: 0) {
                        Text(model.state.title)
                            .font(PIHFont.metaMedium)
                            .foregroundStyle(.primary)
                        Text("系统设置与诊断")
                            .font(PIHFont.meta)
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                    Spacer(minLength: 0)
                    Image(systemName: "chevron.right")
                        .font(PIHFont.sideBarSubtitle)
                        .foregroundStyle(.tertiary)
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 10)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .help("打开设置与运行诊断")
        }
        .background(.bar)
    }

    // MARK: - Detail

    @ViewBuilder
    private var detail: some View {
        switch section ?? .today {
        case .today:
            TodayScreen(
                model: model,
                todayStore: todayStore,
                personalization: personalizationStore,
                onOpenArticle: { id in
                    articlesStore.selectedArticleID = id
                    section = .reading
                },
                onOpenEvent: { id in
                    section = .events
                    Task { await eventStore.select(id) }
                },
                onOpenEvents: { section = .events },
                onOpenReading: { section = .reading },
                onOpenSettings: { section = .settings },
                onEnableAutomation: {
                    Task {
                        await pipelineStore.setAutomation(true)
                        await todayStore.reload(showSpinner: false)
                    }
                },
                onResumeAutomation: {
                    Task {
                        await pipelineStore.setPaused(false)
                        await todayStore.reload(showSpinner: false)
                    }
                }
            )
        case .reading:
            ReadingScreen(
                model: model,
                articlesStore: articlesStore,
                personalization: personalizationStore,
                onOpenEvent: { id in
                    section = .events
                    Task { await eventStore.select(id) }
                }
            )
        case .events:
            EventsScreen(model: model, store: eventStore)
        case .insights:
            InsightsScreen(
                model: model,
                personalization: personalizationStore,
                onOpenFeed: { section = .today },
                onOpenEvent: { id in
                    section = .events
                    Task { await eventStore.select(id) }
                },
                onOpenArticle: { id in
                    articlesStore.selectedArticleID = id
                    section = .reading
                }
            )
        case .settings:
            SettingsScreen(
                model: model,
                sourcesStore: store,
                personalizationStore: personalizationStore,
                pipelineStore: pipelineStore,
                jobsStore: jobsStore,
                aiStore: aiStore,
                articlesStore: articlesStore
            )
        }
    }
}
