import SwiftUI

/// 采集任务：真实触发、分页列表、详情计数、取消/重试与来源健康日志。
struct CollectionJobsScreen: View {
    @ObservedObject var model: SidecarViewModel
    @ObservedObject var store: CollectionJobsStore

    @State private var healthTarget: SourceHealthTarget?

    var body: some View {
        VStack(spacing: 0) {
            toolbar
            Divider().overlay(PIHColor.hairline)
            content
        }
        .frame(minWidth: 900, minHeight: 560)
        .background(PIHColor.canvas)
        .task(id: store.selectedJobID) {
            await store.loadDetail()
        }
        .task {
            // Refresh real job counters whenever the user opens this screen,
            // then keep polling while any job is active.
            await store.reload()
            await store.pollWhileActive()
        }
        .sheet(item: $healthTarget) { target in
            SourceHealthSheet(target: target, client: model.apiClientForFeatures)
        }
    }

    // MARK: - Toolbar

    private var toolbar: some View {
        PIHPageToolbar {
            HStack(spacing: PIHSpacing.control) {
                PageHeader(
                    "采集任务",
                    subtitle: subtitle
                )

                Spacer(minLength: 12)

                Menu {
                    Picker("状态", selection: $store.statusFilter) {
                        ForEach(CollectionJobStatusFilter.allCases) { filter in
                            Text(filter.label).tag(filter)
                        }
                    }
                } label: {
                    Label("筛选", systemImage: "line.3.horizontal.decrease.circle")
                        .font(PIHFont.caption)
                }
                .pihToolbarMenu()
                .onChange(of: store.statusFilter) { _, _ in
                    Task { await store.reload() }
                }

                Button {
                    Task { await store.reload() }
                } label: {
                    Image(systemName: "arrow.clockwise")
                        .font(.system(size: 13, weight: .medium))
                }
                .help("刷新")
                .disabled(store.isLoading)

                Button {
                    Task { await store.createJobForAllEnabledSources() }
                } label: {
                    if store.isCreating {
                        ProgressView().controlSize(.small)
                    } else {
                        Label("采集全部", systemImage: "arrow.triangle.2.circlepath")
                            .font(PIHFont.caption)
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(!model.isDataReady || store.isCreating)
                .help("对全部启用来源触发一次真实采集")
            }
        }
    }

    private var subtitle: String {
        var text = store.hasLoaded ? "共 \(store.total) 个任务" : "尚未加载"
        if store.hasActiveWork {
            text += " · 自动刷新中"
        }
        return text
    }

    // MARK: - Content

    @ViewBuilder
    private var content: some View {
        if !model.isDataReady {
            EmptyPanel(
                icon: "bolt.horizontal.circle",
                title: "本地服务未就绪",
                message: "采集任务需要 Sidecar 正常运行。当前状态：\(model.state.title)。",
                actionTitle: "启动 Sidecar",
                action: { model.start() }
            )
        } else if store.isLoading && !store.hasLoaded {
            LoadingStateView(message: "正在加载采集任务…")
        } else if let message = store.errorMessage, store.jobs.isEmpty {
            EmptyPanel(
                icon: "exclamationmark.triangle",
                title: "采集任务加载失败",
                message: message,
                actionTitle: "重试",
                action: { Task { await store.reload() } }
            )
        } else if store.jobs.isEmpty {
            VStack(spacing: 0) {
                if let message = store.actionErrorMessage {
                    ErrorBanner(
                        message: message,
                        requestID: store.actionErrorRequestID,
                        onRetry: { Task { await store.createJobForAllEnabledSources() } },
                        onDismiss: { store.clearActionError() }
                    )
                    .padding(20)
                }
                EmptyPanel(
                    icon: "arrow.triangle.2.circlepath",
                    title: "还没有采集任务",
                    message: "点击右上角「采集全部」，后端会立即返回 202 并在后台按真实来源并发采集。",
                    actionTitle: "采集全部",
                    action: { Task { await store.createJobForAllEnabledSources() } }
                )
            }
        } else {
            HSplitView {
                listPane
                detailPane
            }
        }
    }

    private var listPane: some View {
        List(selection: $store.selectedJobID) {
            if let message = store.actionErrorMessage {
                Section {
                    ErrorBanner(
                        message: message,
                        requestID: store.actionErrorRequestID,
                        onRetry: nil,
                        onDismiss: { store.clearActionError() }
                    )
                    .listRowSeparator(.hidden)
                }
            }
            if let message = store.errorMessage {
                Section {
                    ErrorBanner(
                        message: message,
                        requestID: store.errorRequestID,
                        onRetry: { Task { await store.reload() } },
                        onDismiss: { store.clearListError() }
                    )
                    .listRowSeparator(.hidden)
                }
            }
            ForEach(store.jobs) { job in
                JobRow(job: job)
                    .tag(job.id)
                    .listRowSeparator(.hidden)
                    .listRowInsets(EdgeInsets(top: 3, leading: 12, bottom: 3, trailing: 12))
            }
            if store.canLoadMore {
                HStack {
                    Spacer()
                    Button {
                        Task { await store.loadMore() }
                    } label: {
                        if store.isLoading {
                            ProgressView().controlSize(.small)
                        } else {
                            Text("加载更多（已显示 \(store.jobs.count) / \(store.total)）")
                                .font(PIHFont.caption)
                        }
                    }
                    .disabled(store.isLoading)
                    Spacer()
                }
                .padding(.vertical, 10)
                .listRowSeparator(.hidden)
            }
        }
        .listStyle(.inset)
        .scrollContentBackground(.hidden)
        .background(PIHColor.canvas)
        .frame(minWidth: 400, idealWidth: 450, maxWidth: 620, maxHeight: .infinity)
    }

    @ViewBuilder
    private var detailPane: some View {
        if let job = store.detail, job.id == store.selectedJobID {
            JobDetailView(
                job: job,
                store: store,
                onOpenHealth: { target in
                    healthTarget = target
                }
            )
        } else if store.selectedJobID != nil {
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
                title: "选择一个采集任务",
                message: "左侧显示真实任务列表；选择后加载来源明细与计数。",
                actionTitle: nil,
                action: nil
            )
        }
    }
}

// MARK: - Job row

private struct JobRow: View {
    let job: CollectionJobDTO

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack(spacing: 8) {
                let status = CollectionJobStatus.resolve(job.status)
                StatusPill(text: status?.label ?? job.status, tint: status?.tint ?? .secondary)
                Text(CollectionTriggerType.label(for: job.triggerType))
                Text(CollectionScope.label(for: job.scope))
                Spacer(minLength: 6)
                Text(PIHDateFormat.displayDetailed(job.createdAt))
                    .monospacedDigit()
                    .foregroundStyle(.secondary)
            }
            .font(PIHFont.meta)

            HStack(spacing: 12) {
                Text("来源 \(job.processedSourceCount)/\(job.requestedSourceCount)")
                Text("成功 \(job.succeededSourceCount)")
                Text("失败 \(job.failedSourceCount)")
                Spacer(minLength: 0)
                Text("新增 \(job.insertedCount) · 重复 \(job.duplicateCount)")
            }
            .font(PIHFont.caption)
            .foregroundStyle(.secondary)

            if let message = job.errorMessage, !message.isEmpty {
                Text(message)
                    .font(PIHFont.meta)
                    .foregroundStyle(.red)
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .pihRowBackground()
        .accessibilityElement(children: .combine)
        .accessibilityLabel(
            "采集任务，状态 \(CollectionJobStatus.label(for: job.status))，"
                + "处理 \(job.processedSourceCount) / \(job.requestedSourceCount) 个来源，"
                + "新增 \(job.insertedCount)，重复 \(job.duplicateCount)，失败 \(job.failedSourceCount)"
        )
    }
}

// MARK: - Job detail

private struct JobDetailView: View {
    let job: CollectionJobDTO
    @ObservedObject var store: CollectionJobsStore
    let onOpenHealth: (SourceHealthTarget) -> Void

    private var status: CollectionJobStatus? {
        CollectionJobStatus.resolve(job.status)
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: PIHSpacing.cardGap) {
                header
                if let message = store.actionErrorMessage {
                    ErrorBanner(
                        message: message,
                        requestID: store.actionErrorRequestID,
                        onRetry: nil,
                        onDismiss: { store.clearActionError() }
                    )
                }
                countsCard
                timingCard
                if let message = job.errorMessage, !message.isEmpty {
                    NoticeBanner(
                        icon: "exclamationmark.triangle.fill",
                        tint: .red,
                        message: message,
                        onDismiss: nil
                    )
                }
                actionBar
                itemsSection
            }
            .padding(.horizontal, 24)
            .padding(.vertical, 22)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .background(PIHColor.canvas)
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                StatusPill(
                    text: status?.label ?? job.status,
                    tint: status?.tint ?? .secondary
                )
                Text(CollectionTriggerType.label(for: job.triggerType))
                Text(CollectionScope.label(for: job.scope))
                if job.cancelRequested {
                    StatusPill(text: "已请求取消", tint: .orange)
                }
                Spacer(minLength: 6)
            }
            .font(PIHFont.caption)
            .foregroundStyle(.secondary)

            Text("任务 ID \(job.id)")
                .font(PIHFont.metaMono)
                .foregroundStyle(.secondary)
                .textSelection(.enabled)
            Text("创建于 \(PIHDateFormat.displayDetailed(job.createdAt))")
                .font(PIHFont.meta)
                .foregroundStyle(.secondary)
        }
    }

    private var countsCard: some View {
        PIHCard {
            Text("来源与文章计数")
                .font(PIHFont.cardTitle)
            HStack(spacing: 14) {
                MetricCell(title: "请求来源", value: job.requestedSourceCount)
                MetricCell(title: "已处理", value: job.processedSourceCount)
                MetricCell(title: "成功", value: job.succeededSourceCount, tint: .green)
                MetricCell(
                    title: "失败",
                    value: job.failedSourceCount,
                    tint: job.failedSourceCount > 0 ? .red : .primary
                )
            }
            Divider().overlay(PIHColor.hairline)
            HStack(spacing: 14) {
                MetricCell(title: "发现", value: job.discoveredCount)
                MetricCell(title: "新增", value: job.insertedCount, tint: .green)
                MetricCell(title: "更新", value: job.updatedCount)
                MetricCell(title: "重复", value: job.duplicateCount)
                MetricCell(
                    title: "错误",
                    value: job.errorCount,
                    tint: job.errorCount > 0 ? .red : .primary
                )
            }
        }
    }

    private var timingCard: some View {
        PIHCard {
            Text("时间")
                .font(PIHFont.cardTitle)
            Grid(alignment: .leading, horizontalSpacing: 24, verticalSpacing: 8) {
                GridRow {
                    Text("开始").foregroundStyle(.secondary)
                    Text(PIHDateFormat.displayDetailed(job.startedAt, empty: status?.isActive == true ? "尚未开始" : "—"))
                }
                GridRow {
                    Text("结束").foregroundStyle(.secondary)
                    Text(PIHDateFormat.displayDetailed(job.finishedAt, empty: status?.isActive == true ? "进行中" : "—"))
                }
                GridRow {
                    Text("耗时").foregroundStyle(.secondary)
                    Text(PIHDuration.display(job.durationMs))
                }
                GridRow {
                    Text("更新时间").foregroundStyle(.secondary)
                    Text(PIHDateFormat.displayDetailed(job.updatedAt))
                }
            }
            .font(PIHFont.caption)
        }
    }

    @ViewBuilder
    private var actionBar: some View {
        HStack(spacing: 10) {
            if let status, status.canCancel {
                Button("取消任务", role: .destructive) {
                    Task { await store.cancel(job) }
                }
                .disabled(store.isPerformingAction)
                .accessibilityLabel("取消采集任务")
            }
            if let status, status.canRetry {
                Button {
                    Task { await store.retry(job) }
                } label: {
                    if store.isPerformingAction {
                        ProgressView().controlSize(.small)
                    } else {
                        Text("重试任务")
                    }
                }
                .disabled(store.isPerformingAction)
                .accessibilityLabel("重试采集任务")
            }
            if job.cancelRequested, status?.isActive == true {
                Text("已请求取消，worker 会在条目边界停止并把未开始条目标记为 cancelled。")
                    .font(PIHFont.meta)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
        }
    }

    private var itemsSection: some View {
        PIHCard {
            HStack {
                Text("来源明细")
                    .font(PIHFont.cardTitle)
                Spacer()
                Text("\(job.items.count) 个来源")
                    .font(PIHFont.meta)
                    .foregroundStyle(.secondary)
            }
            if job.items.isEmpty {
                Text("该响应没有条目明细。列表接口的 items 为空，选择任务后详情接口应返回明细；若持续为空，请检查后端实现。")
                    .font(PIHFont.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            } else {
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(job.items) { item in
                        JobItemRow(item: item) {
                            onOpenHealth(
                                SourceHealthTarget(
                                    sourceID: item.sourceId,
                                    sourceName: item.sourceName ?? item.sourceId
                                )
                            )
                        }
                        if item.id != job.items.last?.id {
                            Divider().overlay(PIHColor.hairline)
                        }
                    }
                }
            }
        }
    }
}

private struct MetricCell: View {
    let title: String
    let value: Int
    var tint: Color = .primary

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title)
                .font(PIHFont.meta)
                .foregroundStyle(.secondary)
            Text("\(value)")
                .font(PIHFont.metricCompact)
                .monospacedDigit()
                .foregroundStyle(tint)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(title) \(value)")
    }
}

private struct JobItemRow: View {
    let item: CollectionJobItemDTO
    let onOpenHealth: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 8) {
                Text(item.sourceName ?? item.sourceId)
                    .font(PIHFont.bodyMedium)
                    .lineLimit(1)
                let status = CollectionJobItemStatus.resolve(item.status)
                StatusPill(text: status?.label ?? item.status, tint: status?.tint ?? .secondary)
                Spacer(minLength: 6)
                Button("健康") { onOpenHealth() }
                    .buttonStyle(.link)
                    .font(PIHFont.meta)
                    .accessibilityLabel("查看 \(item.sourceName ?? item.sourceId) 的健康日志")
            }

            HStack(spacing: 12) {
                Text("HTTP \(item.httpStatus.map(String.init) ?? "—")")
                Text("发现 \(item.discoveredCount)")
                Text("新增 \(item.insertedCount)")
                Text("更新 \(item.updatedCount)")
                Text("重复 \(item.duplicateCount)")
                Text("失败 \(item.errorCount)")
                Text("耗时 \(PIHDuration.display(item.durationMs))")
            }
            .font(PIHFont.meta)
            .foregroundStyle(.secondary)

            if let code = item.errorCode, !code.isEmpty {
                Text(code)
                    .font(PIHFont.meta.weight(.medium))
                    .foregroundStyle(.red)
                    .textSelection(.enabled)
            }
            if let message = item.errorMessage, !message.isEmpty {
                Text(message)
                    .font(PIHFont.meta)
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.vertical, 9)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(
            "来源 \(item.sourceName ?? item.sourceId)，状态 \(CollectionJobItemStatus.label(for: item.status))，"
                + "新增 \(item.insertedCount)，重复 \(item.duplicateCount)，失败 \(item.errorCount)"
        )
    }
}
