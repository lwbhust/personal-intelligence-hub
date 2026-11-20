import SwiftUI

/// 「设置」：把兴趣、信息源、自动化、采集健康、存储与诊断收敛到一处。
///
/// 工程细节（任务 ID、租约、队列扫描耗时）默认折叠在「高级诊断」。
struct SettingsScreen: View {
    enum SectionID: String, CaseIterable, Identifiable {
        case preferences
        case sources
        case automation
        case health
        case storage
        case diagnostics

        var id: String { rawValue }

        var title: String {
            switch self {
            case .preferences: return "兴趣偏好"
            case .sources: return "信息源管理"
            case .automation: return "自动化设置"
            case .health: return "采集健康"
            case .storage: return "存储与备份"
            case .diagnostics: return "高级诊断"
            }
        }

        var icon: String {
            switch self {
            case .preferences: return "slider.horizontal.3"
            case .sources: return "dot.radiowaves.left.and.right"
            case .automation: return "gearshape.2"
            case .health: return "waveform.path.ecg"
            case .storage: return "externaldrive"
            case .diagnostics: return "stethoscope"
            }
        }

        var subtitle: String {
            switch self {
            case .preferences: return "关注领域、阅读预算与屏蔽来源"
            case .sources: return "添加、编辑、停用与立即采集"
            case .automation: return "自动分析、事件聚合与失败重试"
            case .health: return "哪些来源正常、哪些需要处理"
            case .storage: return "数据库位置、版本与备份说明"
            case .diagnostics: return "AI、管道、采集任务与运行状态"
            }
        }
    }

    enum DiagnosticTool: String, CaseIterable, Identifiable {
        case ai
        case pipeline
        case jobs
        case articles
        case categories
        case status

        var id: String { rawValue }
        var title: String {
            switch self {
            case .ai: return "AI 分析"
            case .pipeline: return "自动化管道明细"
            case .jobs: return "采集任务明细"
            case .articles: return "文章高级筛选"
            case .categories: return "分类管理"
            case .status: return "运行状态"
            }
        }
        var icon: String {
            switch self {
            case .ai: return "sparkles"
            case .pipeline: return "gearshape.2"
            case .jobs: return "arrow.triangle.2.circlepath"
            case .articles: return "line.3.horizontal.decrease.circle"
            case .categories: return "folder"
            case .status: return "waveform.path.ecg"
            }
        }
    }

    @ObservedObject var model: SidecarViewModel
    @ObservedObject var sourcesStore: SourcesStore
    @ObservedObject var personalizationStore: PersonalizationStore
    @ObservedObject var pipelineStore: PipelineStore
    @ObservedObject var jobsStore: CollectionJobsStore
    @ObservedObject var aiStore: AIStore
    @ObservedObject var articlesStore: ArticlesStore

    @State private var section: SectionID = .preferences
    @State private var tool: DiagnosticTool?

    var body: some View {
        HSplitView {
            sidebar
            detail
        }
        .frame(minWidth: 760, minHeight: 560)
        .background(PIHColor.canvas)
        .task(id: model.state) {
            guard model.isDataReady else { return }
            await personalizationStore.loadIfNeeded()
            async let sources: Void = sourcesStore.reload()
            async let pipeline: Void = pipelineStore.reloadOverview()
            _ = await (sources, pipeline)
        }
    }

    private var sidebar: some View {
        List(selection: $section) {
            Section {
                ForEach(SectionID.allCases) { item in
                    Label {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(item.title)
                                .font(PIHFont.sideBarLabel)
                            Text(item.subtitle)
                                .font(PIHFont.meta)
                                .foregroundStyle(.secondary)
                                .lineLimit(1)
                        }
                    } icon: {
                        Image(systemName: item.icon)
                            .frame(width: 20)
                    }
                    .tag(item)
                    .padding(.vertical, 4)
                }
            }
        }
        .listStyle(.sidebar)
        .frame(minWidth: 220, idealWidth: 250, maxWidth: 300)
    }

    @ViewBuilder
    private var detail: some View {
        if let tool {
            VStack(spacing: 0) {
                HStack(spacing: 10) {
                    Button {
                        self.tool = nil
                    } label: {
                        Label("返回设置", systemImage: "chevron.left")
                    }
                    .buttonStyle(.plain)
                    Text(tool.title)
                        .font(PIHFont.subsectionTitle)
                    Spacer()
                }
                .padding(.horizontal, PIHSpacing.page)
                .padding(.vertical, 12)
                Divider().overlay(PIHColor.hairline)
                diagnosticView(tool)
            }
        } else {
            ScrollView {
                VStack(alignment: .leading, spacing: PIHSpacing.section) {
                    PageHeader(section.title, subtitle: section.subtitle)
                    switch section {
                    case .preferences:
                        PreferencesSettingsView(store: personalizationStore)
                    case .sources:
                        SourcesScreen(model: model, store: sourcesStore)
                            .frame(minHeight: 620)
                    case .automation:
                        AutomationSettingsView(model: model, store: pipelineStore)
                    case .health:
                        CollectionHealthSettingsView(model: model, store: sourcesStore)
                    case .storage:
                        StorageSettingsView(model: model)
                    case .diagnostics:
                        diagnosticsList
                    }
                }
                .padding(.horizontal, PIHSpacing.page)
                .padding(.vertical, 24)
                .frame(maxWidth: 1080, alignment: .leading)
                .frame(maxWidth: .infinity, alignment: .center)
            }
        }
    }

    @ViewBuilder
    private func diagnosticView(_ tool: DiagnosticTool) -> some View {
        switch tool {
        case .ai:
            AIScreen(model: model, store: aiStore)
        case .pipeline:
            PipelineScreen(model: model, store: pipelineStore)
        case .jobs:
            CollectionJobsScreen(model: model, store: jobsStore)
        case .articles:
            ArticlesScreen(model: model, store: articlesStore)
        case .categories:
            CategoriesScreen(model: model, store: sourcesStore)
        case .status:
            StatusView(model: model)
        }
    }

    private var diagnosticsList: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("普通使用不需要进入这里。以下页面保留完整工程能力，便于排查问题。")
                .font(PIHFont.caption)
                .foregroundStyle(.secondary)
            PIHCard(padding: 8, spacing: 0) {
                ForEach(DiagnosticTool.allCases) { item in
                    Button {
                        tool = item
                    } label: {
                        HStack(spacing: 10) {
                            Image(systemName: item.icon)
                                .frame(width: 22)
                                .foregroundStyle(.secondary)
                            Text(item.title)
                                .font(PIHFont.captionMedium)
                            Spacer()
                            Image(systemName: "chevron.right")
                                .font(PIHFont.meta)
                                .foregroundStyle(.tertiary)
                        }
                        .padding(.horizontal, 10)
                        .padding(.vertical, 10)
                        .pihRowBackground()
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }
}

// MARK: - Preferences

private struct PreferencesSettingsView: View {
    @ObservedObject var store: PersonalizationStore
    @State private var showFullEditor = false

    private let levels = ["core", "extended", "general", "muted"]

    var body: some View {
        VStack(alignment: .leading, spacing: PIHSpacing.section) {
            budgetCard
            interestsCard
            suggestionsCard
            blockedCard
            HStack {
                Spacer()
                Button("高级：完整兴趣画像") { showFullEditor = true }
                    .buttonStyle(.bordered)
            }
        }
        .sheet(isPresented: $showFullEditor) {
            InterestProfileSheet(store: store)
        }
    }

    private var budgetCard: some View {
        PIHCard(padding: 18, spacing: 10) {
            CardHeader("每日阅读预算", icon: "book")
            Text("只影响首页与推荐流展示的条数，不删除任何文章。")
                .font(PIHFont.meta)
                .foregroundStyle(.secondary)
            HStack(spacing: 10) {
                ForEach([5, 10, 20], id: \.self) { value in
                    Button("\(value) 条") {
                        Task { _ = await store.updateProfile(ProfileUpdatePayload(dailyItemLimit: value)) }
                    }
                    .buttonStyle(.bordered)
                    .tint(store.profile?.profile.dailyItemLimit == value ? .accentColor : .secondary)
                }
                Spacer()
                if let profile = store.profile?.profile {
                    Text("当前：\(profile.dailyItemLimit.map(String.init) ?? "默认") 条 / 天")
                        .font(PIHFont.meta)
                        .foregroundStyle(.secondary)
                }
            }
        }
    }

    private var interestsCard: some View {
        PIHCard(padding: 18, spacing: 12) {
            CardHeader("我关注的领域", icon: "target")
            Text("调整关注等级会立即影响后续推荐。关键词与实体权重由系统在后台维护。")
                .font(PIHFont.meta)
                .foregroundStyle(.secondary)
            if store.interests.isEmpty {
                Text("还没有兴趣设置。可在高级编辑器中添加关注领域。")
                    .font(PIHFont.caption)
                    .foregroundStyle(.secondary)
            } else {
                ForEach(levels, id: \.self) { level in
                    let items = store.interests.filter { $0.level == level }
                    if !items.isEmpty {
                        VStack(alignment: .leading, spacing: 6) {
                            Text(levelTitle(level))
                                .font(PIHFont.meta.weight(.semibold))
                                .foregroundStyle(.secondary)
                            ForEach(items) { interest in
                                HStack(spacing: 8) {
                                    Text(interest.name)
                                        .font(PIHFont.captionMedium)
                                    Text(interestTypeLabel(interest.interestType))
                                        .font(PIHFont.meta)
                                        .foregroundStyle(.tertiary)
                                    Spacer()
                                    Menu(levelTitle(interest.level)) {
                                        ForEach(levels, id: \.self) { target in
                                            Button(levelTitle(target)) {
                                                Task {
                                                    _ = await store.updateInterest(
                                                        id: interest.id,
                                                        payload: InterestUpdatePayload(level: target)
                                                    )
                                                }
                                            }
                                        }
                                    }
                                    .menuStyle(.borderlessButton)
                                    .frame(width: 120)
                                }
                                .padding(.vertical, 3)
                            }
                        }
                    }
                }
            }
        }
    }

    @ViewBuilder
    private var suggestionsCard: some View {
        if let suggestions = store.suggestions, !suggestions.items.isEmpty {
            PIHCard(padding: 18, spacing: 10) {
                CardHeader("系统学习建议", icon: "lightbulb")
                Text("这些建议来自你的阅读与反馈，只有点击「采纳」才会改变兴趣等级。")
                    .font(PIHFont.meta)
                    .foregroundStyle(.secondary)
                ForEach(suggestions.items) { suggestion in
                    HStack(spacing: 8) {
                        Text(suggestion.interestName)
                            .font(PIHFont.captionMedium)
                        Text("\(levelTitle(suggestion.currentLevel)) → \(levelTitle(suggestion.suggestedLevel))")
                            .font(PIHFont.meta)
                            .foregroundStyle(.secondary)
                        Spacer()
                        Button("采纳") {
                            Task { await store.applySuggestion(suggestion) }
                        }
                        .buttonStyle(.bordered)
                        .controlSize(.small)
                    }
                }
            }
        }
    }

    private var blockedCard: some View {
        PIHCard(padding: 18, spacing: 10) {
            CardHeader("减少推荐的内容", icon: "eye.slash")
            if store.blockedSources.isEmpty {
                Text("还没有屏蔽任何信息源。可在今日或阅读页对单条内容选择「不感兴趣」。")
                    .font(PIHFont.meta)
                    .foregroundStyle(.secondary)
            } else {
                ForEach(store.blockedSources) { source in
                    HStack(spacing: 8) {
                        Text(source.name)
                            .font(PIHFont.captionMedium)
                        if let reason = source.reason, !reason.isEmpty {
                            Text(reason)
                                .font(PIHFont.meta)
                                .foregroundStyle(.secondary)
                        }
                        Spacer()
                        Button("恢复") {
                            Task { await store.unblockSource(source.sourceId) }
                        }
                        .buttonStyle(.borderless)
                        .controlSize(.small)
                    }
                }
            }
        }
    }

    private func levelTitle(_ level: String) -> String {
        InterestLevel(rawValue: level)?.title ?? level
    }

    private func interestTypeLabel(_ type: String) -> String {
        switch type {
        case "domain": return "领域"
        case "topic": return "主题"
        case "keyword": return "关键词"
        case "entity": return "实体"
        case "source": return "来源"
        default: return type
        }
    }
}

// MARK: - Automation

private struct AutomationSettingsView: View {
    @ObservedObject var model: SidecarViewModel
    @ObservedObject var store: PipelineStore
    @State private var backfillLimit = 100

    var body: some View {
        VStack(alignment: .leading, spacing: PIHSpacing.section) {
            if !model.isDataReady {
                EmptyPanel(
                    icon: "bolt.horizontal.circle",
                    title: "本地服务未就绪",
                    message: "自动化状态需要 Sidecar 运行。",
                    actionTitle: "启动 Sidecar",
                    action: { model.start() }
                )
            } else if let overview = store.overview {
                PIHCard(padding: 20, spacing: 14) {
                    CardHeader("自动处理", icon: "gearshape.2")
                    Toggle("自动分析新文章", isOn: Binding(
                        get: { overview.settings.automationEnabled },
                        set: { value in Task { await store.setAutomation(value) } }
                    ))
                    .toggleStyle(.switch)
                    .disabled(store.isPerformingAction)
                    Text("开启后：新文章 → AI 分析 → 实体提取 → 事件聚合 → 评分 → 推荐刷新。历史文章不会自动全量处理。")
                        .font(PIHFont.meta)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                    HStack(spacing: 10) {
                        Button(overview.settings.paused ? "恢复处理" : "暂停处理") {
                            Task { await store.setPaused(!overview.settings.paused) }
                        }
                        .buttonStyle(.bordered)
                        .disabled(!overview.settings.automationEnabled || store.isPerformingAction)
                        if let message = store.lastActionMessage {
                            Text(message)
                                .font(PIHFont.meta)
                                .foregroundStyle(.secondary)
                        }
                        if let error = store.actionErrorMessage {
                            Text(error)
                                .font(PIHFont.meta)
                                .foregroundStyle(PIHColor.danger)
                        }
                    }
                }

                HStack(spacing: PIHSpacing.cardGap) {
                    MetricCard(
                        title: "等待处理",
                        value: "\(overview.counts.pending + overview.counts.retryWait)",
                        subtitle: "新文章与重试任务",
                        icon: "tray.full",
                        tint: PIHColor.info
                    )
                    MetricCard(
                        title: "今日完成",
                        value: "\(overview.today.succeeded)",
                        subtitle: "失败 \(overview.today.failed) · 跳过 \(overview.today.skipped)",
                        icon: "checkmark.circle",
                        tint: PIHColor.positive
                    )
                    MetricCard(
                        title: "失败任务",
                        value: "\(overview.counts.failed)",
                        subtitle: "可在高级诊断中重试",
                        icon: "exclamationmark.triangle",
                        tint: overview.counts.failed > 0 ? PIHColor.danger : .secondary
                    )
                }

                PIHCard(padding: 18, spacing: 10) {
                    CardHeader("补齐积压", icon: "square.stack.3d.up")
                    if let preview = store.preview {
                        Text("当前有 \(preview.pendingArticles) 篇历史文章尚未完成自动分析。")
                            .font(PIHFont.caption)
                        Text("补齐会创建受控批次，不会超过单批上限。建议先用 20–100 篇确认效果。")
                            .font(PIHFont.meta)
                            .foregroundStyle(.secondary)
                    } else {
                        Text("点击下方按钮读取真实积压数量。")
                            .font(PIHFont.meta)
                            .foregroundStyle(.secondary)
                    }
                    HStack(spacing: 10) {
                        Stepper("每批 \(backfillLimit) 篇", value: $backfillLimit, in: 10...500, step: 10)
                        Button("读取积压") { Task { await store.loadBackfillPreview() } }
                            .buttonStyle(.bordered)
                        Button("创建补齐批次") {
                            Task { _ = await store.createBackfill(limit: backfillLimit) }
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(store.isPerformingAction)
                    }
                }

                if let last = overview.activity.lastCompletedAt {
                    Text("最近完成时间：\(PIHDateFormat.display(last))")
                        .font(PIHFont.meta)
                        .foregroundStyle(.secondary)
                }
            } else if let error = store.overviewErrorMessage {
                EmptyPanel(
                    icon: "exclamationmark.triangle",
                    title: "自动化状态加载失败",
                    message: error,
                    actionTitle: "重试",
                    action: { Task { await store.reloadOverview() } }
                )
            } else {
                LoadingStateView(message: "正在读取自动化状态…")
            }
        }
    }
}

// MARK: - Collection health

private struct CollectionHealthSettingsView: View {
    @ObservedObject var model: SidecarViewModel
    @ObservedObject var store: SourcesStore

    private var enabledSources: [SourceDTO] { store.sources.filter(\.enabled) }
    private var healthy: [SourceDTO] { enabledSources.filter { $0.healthStatus == "healthy" } }
    private var degraded: [SourceDTO] { enabledSources.filter { $0.healthStatus == "degraded" } }
    private var failing: [SourceDTO] { enabledSources.filter { $0.healthStatus == "failing" } }
    private var unknown: [SourceDTO] {
        enabledSources.filter { !["healthy", "degraded", "failing"].contains($0.healthStatus) }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: PIHSpacing.section) {
            HStack(spacing: PIHSpacing.cardGap) {
                MetricCard(title: "正常", value: "\(healthy.count)", subtitle: "最近采集成功", icon: "checkmark.circle", tint: PIHColor.positive)
                MetricCard(title: "偶发异常", value: "\(degraded.count)", subtitle: "可自动重试", icon: "arrow.clockwise", tint: PIHColor.warning)
                MetricCard(title: "持续失败", value: "\(failing.count)", subtitle: "需要处理", icon: "xmark.octagon", tint: PIHColor.danger)
                MetricCard(title: "暂无数据", value: "\(unknown.count)", subtitle: "等待首次采集", icon: "questionmark.circle", tint: .secondary)
            }

            PIHCard(padding: 18, spacing: 10) {
                HStack {
                    CardHeader("需要关注的来源", icon: "waveform.path.ecg")
                    Spacer()
                    Button("全部加载") { Task { await loadAll() } }
                        .buttonStyle(.borderless)
                        .controlSize(.small)
                    Button("刷新") { Task { await store.reload() } }
                        .buttonStyle(.borderless)
                        .controlSize(.small)
                }
                Text("采集成功但没有新文章，不等于来源故障；单次 DNS 失败也不会立即判为失效。")
                    .font(PIHFont.meta)
                    .foregroundStyle(.secondary)
                let attention = (failing + degraded).sorted { ($0.lastErrorAt ?? "") > ($1.lastErrorAt ?? "") }
                if attention.isEmpty {
                    Text("当前没有异常来源。")
                        .font(PIHFont.caption)
                        .foregroundStyle(.secondary)
                } else {
                    ForEach(attention) { source in
                        HStack(alignment: .top, spacing: 10) {
                            StatusPill(
                                text: healthLabel(source.healthStatus),
                                tint: source.healthStatus == "failing" ? PIHColor.danger : PIHColor.warning
                            )
                            VStack(alignment: .leading, spacing: 2) {
                                Text(source.name)
                                    .font(PIHFont.captionMedium)
                                Text(source.lastErrorMessage ?? source.lastErrorCode ?? "尚无错误详情")
                                    .font(PIHFont.meta)
                                    .foregroundStyle(.secondary)
                                    .lineLimit(2)
                                Text("最近成功：\(PIHDateFormat.display(source.lastSuccessAt, empty: "从未"))")
                                    .font(PIHFont.meta)
                                    .foregroundStyle(.tertiary)
                            }
                            Spacer()
                            if store.collectingSourceIDs.contains(source.id) {
                                ProgressView().controlSize(.small)
                            } else {
                                Button("重试") { Task { await store.collect(source) } }
                                    .buttonStyle(.bordered)
                                    .controlSize(.small)
                            }
                        }
                        .padding(.vertical, 4)
                    }
                }
            }

            HStack {
                Spacer()
                Text("来源明细仍可在「信息源管理」中编辑或停用。")
                    .font(PIHFont.meta)
                    .foregroundStyle(.secondary)
            }
        }
        .task { await loadAll() }
    }

    private func loadAll() async {
        await store.reload()
        var guardCount = 0
        while store.sources.count < store.total && guardCount < 4 {
            await store.loadMore()
            guardCount += 1
        }
    }

    private func healthLabel(_ value: String) -> String {
        switch value {
        case "healthy": return "正常"
        case "degraded": return "偶发异常"
        case "failing": return "持续失败"
        default: return "暂无数据"
        }
    }
}

// MARK: - Storage

private struct StorageSettingsView: View {
    @ObservedObject var model: SidecarViewModel

    var body: some View {
        content
    }

    private var content: some View {
        VStack(alignment: .leading, spacing: PIHSpacing.section) {
            PIHCard(padding: 18, spacing: 10) {
                CardHeader("本地数据库", icon: "externaldrive")
                infoRow("数据库状态", model.databaseStatus ?? "未知")
                infoRow("Schema 版本", model.schemaVersion.map(String.init) ?? "未知")
                infoRow("数据位置类型", model.pathKind ?? "未知")
                infoRow("后端版本", model.backendVersion ?? "未知")
                Text("所有文章、阅读状态与推荐结果都保存在本机 SQLite。迁移前会自动备份，不会重建或覆盖现有数据库。")
                    .font(PIHFont.meta)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            PIHCard(padding: 18, spacing: 10) {
                CardHeader("备份与恢复", icon: "arrow.counterclockwise.circle")
                Text("当前版本在数据库迁移与事件聚合 Apply 前自动创建备份，备份文件位于数据库同目录的 backups 文件夹。")
                    .font(PIHFont.meta)
                    .foregroundStyle(.secondary)
                Text("恢复数据库需要退出应用后执行，界面不提供一键恢复，避免误操作覆盖真实数据。")
                    .font(PIHFont.meta)
                    .foregroundStyle(.secondary)
            }
        }
    }

    private func infoRow(_ title: String, _ value: String) -> some View {
        HStack {
            Text(title)
                .font(PIHFont.caption)
                .foregroundStyle(.secondary)
            Spacer()
            Text(value)
                .font(PIHFont.captionMedium)
                .monospacedDigit()
        }
    }
}
