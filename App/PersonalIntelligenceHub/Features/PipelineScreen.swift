import SwiftUI

/// Phase 7.2 全局任务中心：总览 / 正在处理 / 等待处理 / 失败 / 历史 / 自动化设置。
/// 所有数字与状态均来自 `/api/v1/pipeline/*` 真实响应。
struct PipelineScreen: View {
    @ObservedObject var model: SidecarViewModel
    @ObservedObject var store: PipelineStore

    @State private var tab: PipelineTab = .overview

    var body: some View {
        VStack(spacing: 0) {
            toolbar
            Divider().overlay(PIHColor.hairline)
            content
        }
        .frame(minWidth: 900, minHeight: 560)
        .background(PIHColor.canvas)
        .task {
            await store.refreshAll()
        }
        .task(id: tab) {
            switch tab {
            case .running:
                await store.reloadTasks(scope: .running)
            case .waiting:
                await store.reloadTasks(scope: .waiting)
            case .failed:
                await store.reloadTasks(scope: .failed)
            case .history:
                await store.reloadRuns()
            case .overview, .settings:
                await store.refreshAll()
            }
        }
        .task(id: tab) {
            let scope: PipelineTaskScope?
            switch tab {
            case .running: scope = .running
            case .waiting: scope = .waiting
            case .failed: scope = .failed
            default: scope = nil
            }
            await store.pollWhileActive(scope: scope)
        }
        .task(id: store.selectedTaskID) {
            await store.loadDetail()
        }
    }

    // MARK: - Toolbar

    private var toolbar: some View {
        PIHPageToolbar {
            HStack(spacing: PIHSpacing.control) {
                PageHeader("自动化管道", subtitle: subtitle)
                Spacer(minLength: 12)

                if let overview = store.overview {
                    StatusPill(
                        text: overview.automation.enabled ? "自动化开启" : "自动化关闭",
                        tint: overview.automation.enabled ? .green : .secondary
                    )
                    StatusPill(
                        text: overview.automation.paused ? "已暂停" : "运行中",
                        tint: overview.automation.paused ? .orange : .blue
                    )
                    Button(overview.automation.paused ? "恢复" : "暂停") {
                        Task { await store.setPaused(!overview.automation.paused) }
                    }
                    .disabled(store.isPerformingAction || !model.isDataReady)
                    Button(overview.automation.enabled ? "关闭自动化" : "启用自动化") {
                        Task { await store.setAutomation(!overview.automation.enabled) }
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(store.isPerformingAction || !model.isDataReady)
                }

                Button {
                    Task {
                        await store.refreshAll()
                        switch tab {
                        case .running: await store.reloadTasks(scope: .running)
                        case .waiting: await store.reloadTasks(scope: .waiting)
                        case .failed: await store.reloadTasks(scope: .failed)
                        case .history: await store.reloadRuns()
                        case .overview, .settings: break
                        }
                    }
                } label: {
                    Image(systemName: "arrow.clockwise")
                        .font(.system(size: 13, weight: .medium))
                }
                .help("刷新")
            }
        }
    }

    private var subtitle: String {
        guard let overview = store.overview else {
            return model.isDataReady ? "尚未加载" : "本地服务未就绪"
        }
        return "待处理 \(overview.counts.pending) · 运行中 \(overview.counts.running) · 失败 \(overview.counts.failed)"
    }

    // MARK: - Content

    @ViewBuilder
    private var content: some View {
        if !model.isDataReady {
            EmptyPanel(
                icon: "bolt.horizontal.circle",
                title: "本地服务未就绪",
                message: "自动化管道需要 Sidecar 正常运行。当前状态：\(model.state.title)。",
                actionTitle: "启动 Sidecar",
                action: { model.start() }
            )
        } else {
            VStack(spacing: 0) {
                Picker("视图", selection: $tab) {
                    ForEach(PipelineTab.allCases) { item in
                        Text(item.title).tag(item)
                    }
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                .padding(.horizontal, PIHSpacing.page)
                .padding(.vertical, 10)

                Divider().overlay(PIHColor.hairline)

                if let message = store.actionErrorMessage {
                    ErrorBanner(
                        message: message,
                        requestID: store.actionErrorRequestID,
                        onRetry: nil,
                        onDismiss: { store.clearActionError() }
                    )
                    .padding(.horizontal, PIHSpacing.page)
                    .padding(.top, 12)
                }

                tabContent
            }
        }
    }

    @ViewBuilder
    private var tabContent: some View {
        switch tab {
        case .overview:
            PipelineOverviewView(model: model, store: store)
        case .running:
            taskPane(scope: .running, emptyTitle: "当前没有运行中的任务",
                     emptyMessage: "启用自动化后，新文章会自动进入处理管道；也可以手动创建历史回填。")
        case .waiting:
            taskPane(scope: .waiting, emptyTitle: "没有等待处理的任务",
                     emptyMessage: "队列为空。新文章入库或创建回填批次后会出现在这里。")
        case .failed:
            taskPane(scope: .failed, emptyTitle: "没有失败任务",
                     emptyMessage: "失败任务会显示错误码、错误信息与重试次数，可人工重试。")
        case .history:
            PipelineHistoryView(store: store)
        case .settings:
            PipelineSettingsView(store: store)
        }
    }

    private func taskPane(scope: PipelineTaskScope, emptyTitle: String, emptyMessage: String) -> some View {
        Group {
            if store.isLoadingTasks && !store.hasLoadedTasks {
                LoadingStateView(message: "正在加载任务…")
            } else if let message = store.tasksErrorMessage, store.tasks.isEmpty {
                EmptyPanel(
                    icon: "exclamationmark.triangle",
                    title: "任务加载失败",
                    message: message,
                    actionTitle: "重试",
                    action: { Task { await store.reloadTasks(scope: scope) } }
                )
            } else if store.tasks.isEmpty {
                EmptyPanel(
                    icon: "tray",
                    title: emptyTitle,
                    message: emptyMessage,
                    actionTitle: nil,
                    action: nil
                )
            } else {
                HSplitView {
                    taskList(scope: scope)
                    PipelineTaskDetailView(store: store)
                }
            }
        }
    }

    private func taskList(scope: PipelineTaskScope) -> some View {
        List(selection: $store.selectedTaskID) {
            if let message = store.tasksErrorMessage {
                Section {
                    ErrorBanner(
                        message: message,
                        requestID: store.tasksErrorRequestID,
                        onRetry: { Task { await store.reloadTasks(scope: scope) } },
                        onDismiss: { store.clearTasksError() }
                    )
                    .listRowSeparator(.hidden)
                }
            }
            ForEach(store.tasks) { task in
                PipelineTaskRow(task: task)
                    .tag(task.id)
                    .listRowSeparator(.hidden)
                    .listRowInsets(EdgeInsets(top: 3, leading: 12, bottom: 3, trailing: 12))
            }
            if store.canLoadMoreTasks {
                HStack {
                    Spacer()
                    Button {
                        Task { await store.loadMoreTasks(scope: scope) }
                    } label: {
                        if store.isLoadingTasks {
                            ProgressView().controlSize(.small)
                        } else {
                            Text("加载更多（已显示 \(store.tasks.count) / \(store.tasksTotal)）")
                                .font(PIHFont.caption)
                        }
                    }
                    Spacer()
                }
                .padding(.vertical, 10)
                .listRowSeparator(.hidden)
            }
        }
        .listStyle(.inset)
        .scrollContentBackground(.hidden)
        .background(PIHColor.canvas)
        .frame(minWidth: 420, idealWidth: 470, maxWidth: 640, maxHeight: .infinity)
    }
}

// MARK: - Overview

private struct PipelineOverviewView: View {
    @ObservedObject var model: SidecarViewModel
    @ObservedObject var store: PipelineStore
    @State private var backfillLimit = 100
    @State private var showBackfillConfirm = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: PIHSpacing.cardGap) {
                if let overview = store.overview {
                    metrics(overview)
                    automationCard(overview)
                    activityCard(overview)
                    backfillCard(overview)
                    runtimeCard(overview)
                } else if store.isLoadingOverview {
                    LoadingStateView(message: "正在加载管道总览…")
                } else if let message = store.overviewErrorMessage {
                    EmptyPanel(
                        icon: "exclamationmark.triangle",
                        title: "管道总览加载失败",
                        message: message,
                        actionTitle: "重试",
                        action: { Task { await store.reloadOverview() } }
                    )
                } else {
                    EmptyPanel(
                        icon: "gearshape.2",
                        title: "暂无管道数据",
                        message: "可以启用自动化，或先创建一个小批量历史回填。",
                        actionTitle: nil,
                        action: nil
                    )
                }

                if let message = store.lastActionMessage {
                    NoticeBanner(icon: "checkmark.circle.fill", tint: .green, message: message, onDismiss: nil)
                }
            }
            .padding(.horizontal, PIHSpacing.page)
            .padding(.vertical, PIHSpacing.section)
        }
    }

    private func metrics(_ overview: PipelineOverviewDTO) -> some View {
        LazyVGrid(
            columns: [GridItem(.adaptive(minimum: 170), spacing: PIHSpacing.cardGap)],
            spacing: PIHSpacing.cardGap
        ) {
            MetricCard(
                title: "队列待处理",
                value: "\(overview.counts.pending)",
                subtitle: "其中等待重试 \(overview.counts.retryWait)",
                icon: "tray.full",
                tint: .orange
            )
            MetricCard(
                title: "正在运行",
                value: "\(overview.counts.running)",
                subtitle: "单 worker 串行处理",
                icon: "play.circle",
                tint: .blue
            )
            MetricCard(
                title: "今日成功",
                value: "\(overview.today.succeeded)",
                subtitle: "跳过 \(overview.today.skipped)",
                icon: "checkmark.circle",
                tint: .green
            )
            MetricCard(
                title: "今日失败",
                value: "\(overview.today.failed)",
                subtitle: overview.counts.failed > 0 ? "历史累计 \(overview.counts.failed)" : "无失败",
                icon: "exclamationmark.triangle",
                tint: overview.today.failed > 0 ? .red : .secondary
            )
        }
    }

    private func automationCard(_ overview: PipelineOverviewDTO) -> some View {
        PIHCard {
            Text("自动化开关")
                .font(PIHFont.cardTitle)
            HStack(spacing: 18) {
                settingPill("总自动化", overview.automation.enabled)
                settingPill("AI 分析", overview.automation.aiEnabled)
                settingPill("实体同步", overview.automation.entityEnabled)
                settingPill("事件更新", overview.automation.eventEnabled)
                settingPill("评分刷新", overview.automation.scoringEnabled)
            }
            Text("启用自动化只会处理启用后新入库的文章；历史文章需要显式创建回填批次。")
                .font(PIHFont.meta)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private func settingPill(_ title: String, _ on: Bool) -> some View {
        HStack(spacing: 6) {
            Circle().fill(on ? Color.green : Color.secondary).frame(width: 7, height: 7)
            Text(title).font(PIHFont.meta)
            Text(on ? "开" : "关")
                .font(PIHFont.meta.weight(.medium))
                .foregroundStyle(on ? .green : .secondary)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(title)\(on ? "已开启" : "已关闭")")
    }

    private func activityCard(_ overview: PipelineOverviewDTO) -> some View {
        PIHCard {
            Text("最近活动")
                .font(PIHFont.cardTitle)
            Grid(alignment: .leading, horizontalSpacing: 28, verticalSpacing: 8) {
                GridRow {
                    Text("最近完成任务").foregroundStyle(.secondary)
                    Text(PIHDateFormat.displayDetailed(overview.activity.lastCompletedAt))
                }
                GridRow {
                    Text("最近成功").foregroundStyle(.secondary)
                    Text(PIHDateFormat.displayDetailed(overview.activity.lastSucceededAt))
                }
                if let error = overview.activity.lastError, error.errorMessage != nil {
                    GridRow {
                        Text("最近错误").foregroundStyle(.secondary)
                        Text("\(error.errorCode ?? "error") · \(error.errorMessage ?? "")")
                            .foregroundStyle(.red)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
            .font(PIHFont.caption)
        }
    }

    private func backfillCard(_ overview: PipelineOverviewDTO) -> some View {
        PIHCard {
            HStack {
                Text("补齐积压（历史回填）")
                    .font(PIHFont.cardTitle)
                Spacer()
                if store.isLoadingPreview {
                    ProgressView().controlSize(.small)
                }
            }
            if let preview = store.preview {
                Text("待回填文章 \(preview.pendingArticles) 篇，其中 \(preview.aiNeeded) 篇需要 AI 分析、\(preview.eventNeeded) 篇尚未进入事件。")
                    .font(PIHFont.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                Text("预估模型耗时约 \(preview.estimatedTotalMinutes) 分钟（按每篇 10 秒估算，实际取决于模型与机器）。")
                    .font(PIHFont.meta)
                    .foregroundStyle(.tertiary)
                Text(preview.note)
                    .font(PIHFont.meta)
                    .foregroundStyle(.tertiary)
                    .fixedSize(horizontal: false, vertical: true)

                HStack(spacing: 12) {
                    Stepper("本批最多 \(backfillLimit) 篇", value: $backfillLimit, in: 1...200, step: 10)
                        .font(PIHFont.caption)
                    Button {
                        showBackfillConfirm = true
                    } label: {
                        if store.isPerformingAction {
                            ProgressView().controlSize(.small)
                        } else {
                            Text("一键补齐")
                        }
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(preview.pendingArticles == 0 || store.isPerformingAction)
                }
            } else {
                Text("暂时无法读取回填预览。")
                    .font(PIHFont.meta)
                    .foregroundStyle(.secondary)
            }
        }
        .alert("一键补齐积压文章？", isPresented: $showBackfillConfirm) {
            Button("取消", role: .cancel) {}
            Button("创建") {
                Task { _ = await store.createBackfill(limit: backfillLimit) }
            }
        } message: {
            Text("将创建最多 \(backfillLimit) 个持久化任务。即使自动化开关关闭，已创建的回填批次也会在后台按批处理上限执行，可随时暂停。")
        }
    }

    private func runtimeCard(_ overview: PipelineOverviewDTO) -> some View {
        PIHCard {
            Text("运行信息")
                .font(PIHFont.cardTitle)
            Grid(alignment: .leading, horizontalSpacing: 28, verticalSpacing: 8) {
                GridRow {
                    Text("调度线程").foregroundStyle(.secondary)
                    Text(overview.runtime.workerAlive ? "运行中" : "未运行")
                        .foregroundStyle(overview.runtime.workerAlive ? .green : .orange)
                }
                GridRow {
                    Text("最近扫描").foregroundStyle(.secondary)
                    Text(PIHDateFormat.displayDetailed(overview.runtime.lastSweepAt))
                }
                GridRow {
                    Text("扫描耗时").foregroundStyle(.secondary)
                    Text(overview.runtime.lastSweepDurationMs.map { "\($0) ms" } ?? "—")
                }
                if let error = overview.runtime.lastSweepError {
                    GridRow {
                        Text("扫描错误").foregroundStyle(.secondary)
                        Text(error).foregroundStyle(.red)
                    }
                }
                GridRow {
                    Text("启动时恢复任务").foregroundStyle(.secondary)
                    Text("\(overview.runtime.lastRecoveredTasks)")
                }
                GridRow {
                    Text("分类字典 / 评分版本").foregroundStyle(.secondary)
                    Text("\(overview.taxonomyVersion) · \(overview.scoreVersion)")
                }
            }
            .font(PIHFont.caption)
        }
    }
}

// MARK: - Task row

private struct PipelineTaskRow: View {
    let task: PipelineTaskDTO

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 8) {
                StatusPill(text: PipelineTaskStatus.label(task.status), tint: PipelineTaskStatus.tint(task.status))
                Text(PipelineStage.label(task.stage))
                Text(PipelineTrigger.label(task.triggerType))
                Spacer(minLength: 6)
                Text("尝试 \(task.attempts)/\(task.maxAttempts)")
                    .monospacedDigit()
            }
            .font(PIHFont.meta)

            Text(task.articleTitle ?? "任务 \(task.id.prefix(8))")
                .font(PIHFont.bodyMedium)
                .lineLimit(1)

            HStack(spacing: 10) {
                if let source = task.sourceName { Text(source) }
                Text(PIHDateFormat.displayDetailed(task.updatedAt))
                Spacer(minLength: 0)
            }
            .font(PIHFont.meta)
            .foregroundStyle(.secondary)

            if let message = task.errorMessage, !message.isEmpty {
                Text("\(task.errorCode ?? "error") · \(message)")
                    .font(PIHFont.meta)
                    .foregroundStyle(.red)
                    .lineLimit(2)
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .pihRowBackground()
        .accessibilityElement(children: .combine)
        .accessibilityLabel(
            "管道任务，状态 \(PipelineTaskStatus.label(task.status))，"
                + "阶段 \(PipelineStage.label(task.stage))，尝试 \(task.attempts) 次"
        )
    }
}

// MARK: - Task detail

private struct PipelineTaskDetailView: View {
    @ObservedObject var store: PipelineStore

    var body: some View {
        Group {
            if let task = store.detail, task.id == store.selectedTaskID {
                ScrollView {
                    VStack(alignment: .leading, spacing: PIHSpacing.cardGap) {
                        header(task)
                        progressCard(task)
                        metadataCard(task)
                        if let output = task.outputSummary, !output.isEmpty {
                            summaryCard(title: "输出摘要", text: output)
                        }
                        if let input = task.inputSummary, !input.isEmpty {
                            summaryCard(title: "输入摘要", text: input)
                        }
                        actionBar(task)
                        logsCard
                    }
                    .padding(.horizontal, 24)
                    .padding(.vertical, 22)
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
                .background(PIHColor.canvas)
            } else if store.selectedTaskID != nil {
                if store.isLoadingDetail {
                    LoadingStateView(message: "正在加载任务详情…")
                } else if let message = store.detailErrorMessage {
                    EmptyPanel(
                        icon: "exclamationmark.triangle",
                        title: "任务详情加载失败",
                        message: message,
                        actionTitle: "重试",
                        action: { Task { await store.loadDetail(force: true) } }
                    )
                } else {
                    LoadingStateView(message: "正在准备任务详情…")
                }
            } else {
                EmptyPanel(
                    icon: "list.bullet.rectangle",
                    title: "选择一个任务",
                    message: "左侧显示真实任务列表；选择后加载阶段、错误与处理日志。",
                    actionTitle: nil,
                    action: nil
                )
            }
        }
    }

    private func header(_ task: PipelineTaskDTO) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                StatusPill(text: PipelineTaskStatus.label(task.status), tint: PipelineTaskStatus.tint(task.status))
                Text(PipelineStage.label(task.stage))
                Text(PipelineTrigger.label(task.triggerType))
                if task.batchId != nil {
                    StatusPill(text: "回填批次", tint: .purple)
                }
            }
            .font(PIHFont.caption)
            .foregroundStyle(.secondary)

            Text(task.articleTitle ?? "任务 \(task.id)")
                .font(PIHFont.sectionTitle)
                .fixedSize(horizontal: false, vertical: true)
            Text("任务 ID \(task.id)")
                .font(PIHFont.metaMono)
                .foregroundStyle(.secondary)
                .textSelection(.enabled)
        }
    }

    private func progressCard(_ task: PipelineTaskDTO) -> some View {
        PIHCard {
            Text("处理阶段")
                .font(PIHFont.cardTitle)
            HStack(spacing: 6) {
                ForEach(Array(PipelineStage.order.enumerated()), id: \.offset) { index, stage in
                    let reached = index <= PipelineStage.index(task.stage)
                    VStack(spacing: 4) {
                        Circle()
                            .fill(reached ? Color.accentColor : Color.secondary.opacity(0.25))
                            .frame(width: 8, height: 8)
                        Text(PipelineStage.label(stage))
                            .font(.system(size: 10))
                            .foregroundStyle(reached ? .primary : .secondary)
                    }
                    .frame(maxWidth: .infinity)
                }
            }
            if task.status == "skipped" {
                Text("该任务已跳过：\(task.errorCode ?? "未知原因")")
                    .font(PIHFont.meta)
                    .foregroundStyle(.orange)
            }
        }
    }

    private func metadataCard(_ task: PipelineTaskDTO) -> some View {
        PIHCard {
            Text("任务信息")
                .font(PIHFont.cardTitle)
            Grid(alignment: .leading, horizontalSpacing: 28, verticalSpacing: 8) {
                GridRow { Text("来源").foregroundStyle(.secondary); Text(task.sourceName ?? "—") }
                GridRow { Text("关联事件").foregroundStyle(.secondary); Text(task.eventId ?? "—") }
                GridRow { Text("创建时间").foregroundStyle(.secondary); Text(PIHDateFormat.displayDetailed(task.createdAt)) }
                GridRow { Text("开始时间").foregroundStyle(.secondary); Text(PIHDateFormat.displayDetailed(task.startedAt)) }
                GridRow { Text("更新时间").foregroundStyle(.secondary); Text(PIHDateFormat.displayDetailed(task.updatedAt)) }
                GridRow { Text("完成时间").foregroundStyle(.secondary); Text(PIHDateFormat.displayDetailed(task.completedAt)) }
                GridRow { Text("下次重试").foregroundStyle(.secondary); Text(PIHDateFormat.displayDetailed(task.nextRetryAt)) }
                GridRow {
                    Text("尝试次数").foregroundStyle(.secondary)
                    Text("\(task.attempts) / \(task.maxAttempts)")
                }
                if let code = task.errorCode {
                    GridRow {
                        Text("错误码").foregroundStyle(.secondary)
                        Text(code).foregroundStyle(.red).textSelection(.enabled)
                    }
                }
                if let message = task.errorMessage {
                    GridRow {
                        Text("错误信息").foregroundStyle(.secondary)
                        Text(message).foregroundStyle(.red).fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
            .font(PIHFont.caption)
        }
    }

    private func summaryCard(title: String, text: String) -> some View {
        PIHCard {
            Text(title)
                .font(PIHFont.cardTitle)
            Text(text)
                .font(PIHFont.metaMono)
                .foregroundStyle(.secondary)
                .textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private func actionBar(_ task: PipelineTaskDTO) -> some View {
        HStack(spacing: 10) {
            if task.status != "running" {
                Button("重试任务") {
                    Task { await store.retrySelected() }
                }
                .disabled(store.isPerformingAction)
            }
            if task.status == "pending" || task.status == "ready" || task.status == "retry_wait" {
                Button("取消任务", role: .destructive) {
                    Task { await store.cancelSelected() }
                }
                .disabled(store.isPerformingAction)
            }
            if task.status == "running" {
                Text("运行中的任务不能强制取消，避免数据库状态不一致。")
                    .font(PIHFont.meta)
                    .foregroundStyle(.secondary)
            }
            Spacer(minLength: 0)
        }
    }

    private var logsCard: some View {
        PIHCard {
            HStack {
                Text("处理日志")
                    .font(PIHFont.cardTitle)
                Spacer()
                Text("\(store.logs.count) 条")
                    .font(PIHFont.meta)
                    .foregroundStyle(.secondary)
            }
            if store.logs.isEmpty {
                Text("暂无日志。任务开始执行后会记录每个阶段的真实结果。")
                    .font(PIHFont.meta)
                    .foregroundStyle(.secondary)
            } else {
                VStack(alignment: .leading, spacing: 10) {
                    ForEach(store.logs) { log in
                        VStack(alignment: .leading, spacing: 3) {
                            HStack(spacing: 8) {
                                StatusPill(
                                    text: log.level,
                                    tint: log.level == "error" ? .red : (log.level == "warn" ? .orange : .secondary)
                                )
                                if let stage = log.stage {
                                    Text(PipelineStage.label(stage))
                                        .font(PIHFont.meta)
                                        .foregroundStyle(.secondary)
                                }
                                Spacer(minLength: 0)
                                Text(PIHDateFormat.displayDetailed(log.createdAt))
                                    .font(PIHFont.meta)
                                    .foregroundStyle(.tertiary)
                            }
                            Text(log.message)
                                .font(PIHFont.caption)
                                .fixedSize(horizontal: false, vertical: true)
                            if !log.detail.isEmpty {
                                Text(log.detail.map { "\($0.key)=\($0.value.display)" }.sorted().joined(separator: " · "))
                                    .font(PIHFont.meta)
                                    .foregroundStyle(.tertiary)
                                    .textSelection(.enabled)
                            }
                        }
                    }
                }
            }
        }
    }
}

// MARK: - History

private struct PipelineHistoryView: View {
    @ObservedObject var store: PipelineStore

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: PIHSpacing.cardGap) {
                PIHCard {
                    HStack {
                        Text("回填批次")
                            .font(PIHFont.cardTitle)
                        Spacer()
                        Text("共 \(store.runsTotal) 个")
                            .font(PIHFont.meta)
                            .foregroundStyle(.secondary)
                    }
                    if store.runs.isEmpty {
                        Text("还没有历史回填批次。可在「总览」中创建限量回填。")
                            .font(PIHFont.meta)
                            .foregroundStyle(.secondary)
                    } else {
                        VStack(spacing: 0) {
                            ForEach(store.runs) { run in
                                runRow(run)
                                if run.id != store.runs.last?.id {
                                    Divider().overlay(PIHColor.hairline)
                                }
                            }
                        }
                    }
                }
            }
            .padding(.horizontal, PIHSpacing.page)
            .padding(.vertical, PIHSpacing.section)
        }
    }

    private func runRow(_ run: PipelineRunDTO) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 8) {
                StatusPill(text: PipelineRunStatus.label(run.status), tint: PipelineRunStatus.tint(run.status))
                Text("请求 \(run.requestedTasks) · 创建 \(run.createdTasks)")
                Spacer(minLength: 6)
                Text(PIHDateFormat.displayDetailed(run.createdAt))
                    .foregroundStyle(.secondary)
                    .monospacedDigit()
            }
            .font(PIHFont.meta)
            HStack(spacing: 12) {
                Text("已处理 \(run.processedTasks)")
                Text("成功 \(run.succeededTasks)")
                Text("失败 \(run.failedTasks)")
                Text("跳过 \(run.skippedTasks)")
                Spacer(minLength: 0)
                if !["succeeded", "partially_succeeded", "failed", "cancelled"].contains(run.status) {
                    Button("取消批次", role: .destructive) {
                        Task { await store.cancelRun(run) }
                    }
                    .font(PIHFont.meta)
                    .disabled(store.isPerformingAction)
                }
            }
            .font(PIHFont.caption)
            .foregroundStyle(.secondary)
            if let message = run.errorMessage, !message.isEmpty {
                Text(message)
                    .font(PIHFont.meta)
                    .foregroundStyle(.red)
            }
        }
        .padding(.vertical, 9)
    }
}

// MARK: - Settings

private struct PipelineSettingsView: View {
    @ObservedObject var store: PipelineStore

    @State private var automationEnabled = false
    @State private var aiEnabled = true
    @State private var entityEnabled = true
    @State private var eventEnabled = true
    @State private var scoringEnabled = true
    @State private var batchSize = 3
    @State private var maxAttempts = 3
    @State private var aiInterval = 30

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: PIHSpacing.cardGap) {
                PIHCard {
                    Text("自动化开关")
                        .font(PIHFont.cardTitle)
                    Toggle("总自动化（新文章自动进入管道）", isOn: $automationEnabled)
                    Toggle("AI 分析自动执行", isOn: $aiEnabled)
                    Toggle("实体同步自动执行", isOn: $entityEnabled)
                    Toggle("事件更新自动执行", isOn: $eventEnabled)
                    Toggle("事件评分自动刷新", isOn: $scoringEnabled)
                    Text("关闭总自动化后，实时文章不再入队；显式创建的回填任务仍需手动暂停才会停止。")
                        .font(PIHFont.meta)
                        .foregroundStyle(.secondary)
                }

                PIHCard {
                    Text("资源与重试")
                        .font(PIHFont.cardTitle)
                    Stepper("每轮处理上限：\(batchSize) 个任务", value: $batchSize, in: 1...20)
                    Stepper("失败最大尝试次数：\(maxAttempts) 次", value: $maxAttempts, in: 1...6)
                    Stepper("AI 调用最小间隔：\(aiInterval) 秒", value: $aiInterval, in: 0...600, step: 10)
                    Text("AI 单 worker 串行调用本地 Ollama；间隔用于避免长时间占满机器资源。")
                        .font(PIHFont.meta)
                        .foregroundStyle(.secondary)
                }

                HStack(spacing: 12) {
                    Button {
                        Task {
                            _ = await store.saveSettings(
                                PipelineSettingsUpdate(
                                    automationEnabled: automationEnabled,
                                    aiEnabled: aiEnabled,
                                    entityEnabled: entityEnabled,
                                    eventEnabled: eventEnabled,
                                    scoringEnabled: scoringEnabled,
                                    batchSize: batchSize,
                                    maxAttempts: maxAttempts,
                                    aiIntervalSeconds: aiInterval
                                )
                            )
                        }
                    } label: {
                        if store.isPerformingAction {
                            ProgressView().controlSize(.small)
                        } else {
                            Text("保存设置")
                        }
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(store.isPerformingAction)

                    if let message = store.lastActionMessage {
                        Text(message)
                            .font(PIHFont.meta)
                            .foregroundStyle(.secondary)
                    }
                    Spacer(minLength: 0)
                }
            }
            .padding(.horizontal, PIHSpacing.page)
            .padding(.vertical, PIHSpacing.section)
        }
        .task { syncFromStore() }
        .onChange(of: store.overview?.settings) { _, _ in syncFromStore() }
    }

    private func syncFromStore() {
        guard let settings = store.overview?.settings else { return }
        automationEnabled = settings.automationEnabled
        aiEnabled = settings.aiEnabled
        entityEnabled = settings.entityEnabled
        eventEnabled = settings.eventEnabled
        scoringEnabled = settings.scoringEnabled
        batchSize = settings.batchSize
        maxAttempts = settings.maxAttempts
        aiInterval = settings.aiIntervalSeconds
    }
}
