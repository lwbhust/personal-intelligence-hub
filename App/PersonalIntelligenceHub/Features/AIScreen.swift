import SwiftUI

/// 本地 AI 分析页：真实状态、模型白名单与运行记录。
struct AIScreen: View {
    @ObservedObject var model: SidecarViewModel
    @ObservedObject var store: AIStore

    var body: some View {
        VStack(spacing: 0) {
            toolbar
            Divider().overlay(PIHColor.hairline)
            if let message = store.errorMessage {
                ErrorBanner(
                    message: message,
                    requestID: nil,
                    onRetry: { Task { await store.reload() } },
                    onDismiss: { store.clearError() }
                )
                .padding(.horizontal, PIHSpacing.page)
                .padding(.top, 12)
            }
            if let message = store.actionMessage {
                NoticeBanner(
                    icon: "checkmark.circle",
                    tint: .green,
                    message: message,
                    onDismiss: nil
                )
                .padding(.horizontal, PIHSpacing.page)
                .padding(.top, 12)
            }
            content
        }
        .background(PIHColor.canvas)
        .task { await store.reload() }
        .task { await store.autoRefreshLoop() }
    }

    // MARK: - Toolbar

    private var toolbar: some View {
        PIHPageToolbar {
            HStack(spacing: PIHSpacing.control) {
                PageHeader(
                    "AI 分析",
                    subtitle: "本机 Ollama · 模型白名单与真实运行记录"
                )

                Spacer(minLength: 12)

                Stepper(value: $store.runLimit, in: 1...200, step: 10) {
                    Text("单次上限 \(store.runLimit) 篇")
                        .font(PIHFont.caption)
                        .foregroundStyle(.secondary)
                }
                .frame(width: 190)

                Button {
                    Task { await store.createUnanalyzedRun() }
                } label: {
                    Label("分析未分析文章", systemImage: "sparkles")
                        .font(PIHFont.caption)
                }
                .buttonStyle(.borderedProminent)
                .disabled(!(store.status?.enabled ?? false) || store.isBusy)

                if store.isLoading || store.isBusy {
                    ProgressView().controlSize(.small)
                }

                Button {
                    Task { await store.reload() }
                } label: {
                    Image(systemName: "arrow.clockwise")
                        .font(.system(size: 13, weight: .medium))
                }
                .help("刷新")
                .disabled(store.isLoading)
            }
        }
    }

    // MARK: - Content

    @ViewBuilder
    private var content: some View {
        if !store.hasLoaded && store.isLoading {
            LoadingStateView(message: "正在读取本地 AI 状态…")
        } else if store.hasLoaded {
            HSplitView {
                ScrollView {
                    VStack(alignment: .leading, spacing: PIHSpacing.cardGap) {
                        statusCard
                        modelsCard
                    }
                    .padding(.horizontal, 20)
                    .padding(.vertical, 20)
                }
                .frame(minWidth: 340, idealWidth: 400, maxWidth: 480)

                runsPanel
                    .frame(minWidth: 480)
            }
        } else {
            EmptyPanel(
                icon: "sparkles",
                title: "无法读取 AI 状态",
                message: store.errorMessage ?? "Sidecar 未就绪。",
                actionTitle: "重试",
                action: { Task { await store.reload() } }
            )
        }
    }

    private var statusCard: some View {
        PIHCard {
            HStack(spacing: 8) {
                Text("Provider 状态")
                    .font(PIHFont.cardTitle)
                if let status = store.status {
                    StatusPill(
                        text: status.enabled ? (status.available ? "可用" : "降级") : "已禁用",
                        tint: !status.enabled ? .secondary : (status.available ? .green : .orange)
                    )
                }
                Spacer()
            }
            if let status = store.status {
                Grid(alignment: .leading, horizontalSpacing: 14, verticalSpacing: 8) {
                    row("Provider", status.providerKind)
                    row("地址", status.baseUrl)
                    row("Ollama 版本", status.version ?? "不可用")
                    row("默认模型", status.defaultModel ?? "未配置")
                    row("已启用模型", status.enabledModels.joined(separator: "、"))
                    row("已安装模型", status.installedModels.isEmpty ? "—" : status.installedModels.joined(separator: "、"))
                    row("云端模型阻断数", String(status.cloudModelsBlocked))
                    row("并发 / 队列", "\(status.concurrency) / \(status.queueDepth)")
                    row("Embedding", status.embedding.enabled ? "已启用" : "未启用（\(status.embedding.reason ?? "未配置")）")
                    row("检查时间", PIHDateFormat.display(status.checkedAt))
                }
                .font(PIHFont.caption)
                if !status.available {
                    Text("Ollama 当前不可用：分析任务会失败并标记 model_unavailable，阅读与采集不受影响。")
                        .font(PIHFont.meta)
                        .foregroundStyle(.orange)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }

    private var modelsCard: some View {
        PIHCard {
            Text("模型白名单")
                .font(PIHFont.cardTitle)
            Text("只有启用的本地模型会被调用；任何 *-cloud 模型在 Provider 与数据库层均被拒绝。")
                .font(PIHFont.meta)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            ForEach(store.models) { item in
                VStack(alignment: .leading, spacing: 4) {
                    HStack(spacing: 6) {
                        Text(item.modelName)
                            .font(PIHFont.bodyMedium)
                        StatusPill(
                            text: item.enabled ? "已启用" : "未启用",
                            tint: item.enabled ? .green : .secondary
                        )
                        if !item.installed {
                            StatusPill(text: "未安装", tint: .orange)
                        }
                        Spacer()
                    }
                    Text(
                        "num_ctx \(item.numCtx) · \(item.parameterSize ?? "—") · \(item.quantization ?? "—") · 角色 \(item.roles.joined(separator: ","))"
                    )
                    .font(PIHFont.meta)
                    .foregroundStyle(.secondary)
                    if let digest = item.digest, !digest.isEmpty {
                        Text("digest \(digest.prefix(16))…")
                            .font(PIHFont.metaMono)
                            .foregroundStyle(.tertiary)
                    }
                }
                .padding(.vertical, 5)
            }
        }
    }

    private func row(_ label: String, _ value: String) -> some View {
        GridRow {
            Text(label).foregroundStyle(.secondary)
            Text(value.isEmpty ? "—" : value)
                .textSelection(.enabled)
        }
    }

    // MARK: - Runs

    private var runsPanel: some View {
        VStack(spacing: 0) {
            HStack {
                Text("分析任务")
                    .font(PIHFont.cardTitle)
                Spacer()
                if let run = store.selectedRun {
                    runActions(run)
                }
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 14)
            Divider().overlay(PIHColor.hairline)

            if store.runs.isEmpty {
                EmptyPanel(
                    icon: "tray",
                    title: "暂无分析任务",
                    message: "点击「分析未分析文章」后，这里会显示真实运行状态与逐篇结果。",
                    actionTitle: nil,
                    action: nil
                )
            } else {
                HSplitView {
                    List(selection: Binding(
                        get: { store.selectedRunID },
                        set: { newValue in Task { await store.selectRun(newValue) } }
                    )) {
                        ForEach(store.runs) { run in
                            runRow(run)
                                .tag(run.id)
                                .listRowSeparator(.hidden)
                                .listRowInsets(EdgeInsets(top: 3, leading: 10, bottom: 3, trailing: 10))
                        }
                    }
                    .listStyle(.inset)
                    .scrollContentBackground(.hidden)
                    .background(PIHColor.canvas)
                    .frame(minWidth: 250, idealWidth: 290, maxWidth: 380)

                    runDetail
                        .frame(minWidth: 320)
                }
            }
        }
    }

    private func runRow(_ run: AIRunDTO) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(spacing: 6) {
                StatusPill(
                    text: aiRunStatusLabel(run.status),
                    tint: AIRunStatus(rawValue: run.status)?.tint ?? .secondary
                )
                Text(run.modelName ?? "—")
                    .font(PIHFont.meta)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                Spacer(minLength: 0)
            }
            Text("\(run.processedCount)/\(run.requestedCount) · 成功 \(run.succeededCount) · 失败 \(run.failedCount)")
                .font(PIHFont.meta)
                .foregroundStyle(.secondary)
            Text(PIHDateFormat.display(run.createdAt))
                .font(PIHFont.meta)
                .foregroundStyle(.tertiary)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
        .pihRowBackground()
    }

    @ViewBuilder
    private var runDetail: some View {
        if let run = store.selectedRun {
            ScrollView {
                runDetailContent(run)
                    .padding(.horizontal, 20)
                    .padding(.vertical, 18)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        } else {
            EmptyPanel(
                icon: "list.bullet.rectangle",
                title: "选择一个任务",
                message: "选择左侧任务可查看逐篇分析与错误原因。",
                actionTitle: nil,
                action: nil
            )
        }
    }

    private func runDetailContent(_ run: AIRunDTO) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 8) {
                StatusPill(
                    text: aiRunStatusLabel(run.status),
                    tint: AIRunStatus(rawValue: run.status)?.tint ?? .secondary
                )
                Text(String(run.id.prefix(8)))
                    .font(PIHFont.metaMono)
                    .foregroundStyle(.secondary)
            }
            runSummaryGrid(run)
            if run.items.isEmpty {
                Text("暂无逐篇明细。")
                    .font(PIHFont.caption)
                    .foregroundStyle(.secondary)
            } else {
                Text("逐篇结果")
                    .font(PIHFont.cardTitle)
                runItemsList(run)
            }
        }
    }

    private func runSummaryGrid(_ run: AIRunDTO) -> some View {
        Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 7) {
            GridRow {
                Text("范围").foregroundStyle(.secondary)
                Text(run.scope == "selected" ? "指定文章" : "未分析文章")
            }
            GridRow {
                Text("模型").foregroundStyle(.secondary)
                Text(run.modelName ?? "—")
            }
            GridRow {
                Text("进度").foregroundStyle(.secondary)
                Text("\(run.processedCount)/\(run.requestedCount)")
            }
            GridRow {
                Text("成功 / 失败 / 跳过").foregroundStyle(.secondary)
                Text("\(run.succeededCount) / \(run.failedCount) / \(run.skippedCount)")
            }
            GridRow {
                Text("耗时").foregroundStyle(.secondary)
                Text(PIHDuration.display(run.durationMs))
            }
            GridRow {
                Text("创建时间").foregroundStyle(.secondary)
                Text(PIHDateFormat.display(run.createdAt))
            }
            if let error = run.errorMessage {
                GridRow {
                    Text("错误").foregroundStyle(.secondary)
                    Text(error)
                }
            }
        }
        .font(PIHFont.caption)
    }

    private func runItemsList(_ run: AIRunDTO) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            ForEach(run.items) { item in
                VStack(alignment: .leading, spacing: 4) {
                    HStack(spacing: 6) {
                        StatusPill(
                            text: aiItemStatusLabel(item.status),
                            tint: itemTint(item.status)
                        )
                        Text(item.articleTitle ?? String(item.articleId.prefix(8)))
                            .font(PIHFont.body)
                            .lineLimit(2)
                    }
                    HStack(spacing: 10) {
                        Text("尝试 \(item.attempts) 次")
                        Text("耗时 \(PIHDuration.display(item.durationMs))")
                        if let code = item.errorCode {
                            Text(aiErrorLabel(code))
                                .foregroundStyle(.red)
                        }
                    }
                    .font(PIHFont.meta)
                    .foregroundStyle(.secondary)
                }
                .padding(.vertical, 4)
            }
        }
    }

    @ViewBuilder
    private func runActions(_ run: AIRunDTO) -> some View {
        HStack(spacing: 8) {
            if run.status == "running" || run.status == "pending" {
                Button("暂停") { Task { await store.pause(run) } }
                    .disabled(store.isBusy)
            }
            if run.status == "paused" {
                Button("恢复") { Task { await store.resume(run) } }
                    .disabled(store.isBusy)
            }
            if ["pending", "running", "paused"].contains(run.status) {
                Button("取消", role: .destructive) { Task { await store.cancel(run) } }
                    .disabled(store.isBusy)
            }
            if ["failed", "partially_succeeded", "cancelled"].contains(run.status) {
                Button("重试") { Task { await store.retry(run) } }
                    .disabled(store.isBusy)
            }
        }
        .controlSize(.small)
        .font(PIHFont.caption)
    }

    private func itemTint(_ status: String) -> Color {
        switch status {
        case "succeeded": return .green
        case "running": return .blue
        case "failed": return .red
        default: return .secondary
        }
    }
}

extension AIRunStatus {
    var tint: Color {
        switch self {
        case .pending: return .secondary
        case .running: return .blue
        case .paused: return .orange
        case .succeeded: return .green
        case .partiallySucceeded: return .orange
        case .failed: return .red
        case .cancelled: return .gray
        }
    }
}
