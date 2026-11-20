import SwiftUI

struct SourcesScreen: View {
    @ObservedObject var model: SidecarViewModel
    @ObservedObject var store: SourcesStore

    @State private var editor: SourceDraft?
    @State private var deleting: SourceDTO?
    @State private var healthTarget: SourceHealthTarget?
    @State private var adapterTarget: SourceDTO?

    var body: some View {
        VStack(spacing: 0) {
            toolbar
            Divider().overlay(PIHColor.hairline)
            content
        }
        .frame(minWidth: 720, minHeight: 520)
        .background(PIHColor.canvas)
        .sheet(item: $editor) { draft in
            SourceEditorView(store: store, draft: draft)
        }
        .alert(
            "删除信息源？",
            isPresented: Binding(
                get: { deleting != nil },
                set: { if !$0 { deleting = nil } }
            ),
            presenting: deleting
        ) { source in
            Button("删除", role: .destructive) {
                Task {
                    await store.delete(source)
                    deleting = nil
                }
            }
            Button("取消", role: .cancel) { deleting = nil }
        } message: { source in
            Text("「\(source.name)」将被软删除并从列表隐藏；不会影响其它信息源。")
        }
        .task(id: store.searchText) {
            try? await Task.sleep(for: .milliseconds(300))
            guard !Task.isCancelled else { return }
            await store.reload()
        }
    }

    // MARK: - Toolbar

    private var toolbar: some View {
        PIHPageToolbar {
            HStack(spacing: PIHSpacing.control) {
                PageHeader(
                    "信息源",
                    subtitle: store.hasLoaded ? "共 \(store.total) 个 · 真实写入本地 SQLite" : "尚未加载"
                )

                Spacer(minLength: 12)

                SearchField(placeholder: "搜索信息源名称", text: $store.searchText, width: 200)

                Menu {
                    Picker("类型", selection: $store.typeFilter) {
                        ForEach(SourceTypeFilter.allCases) { filter in
                            Text(filter.label).tag(filter)
                        }
                    }
                    Picker("状态", selection: $store.enabledFilter) {
                        ForEach(EnabledFilter.allCases) { filter in
                            Text(filter.label).tag(filter)
                        }
                    }
                    Picker("分类", selection: $store.categoryFilter) {
                        Text("全部分类").tag(String?.none)
                        ForEach(store.categories) { category in
                            Text(category.name).tag(Optional(category.id))
                        }
                    }
                    Picker("语言", selection: $store.languageFilter) {
                        Text("全部语言").tag(String?.none)
                        Text("中文").tag(Optional("zh"))
                        Text("英文").tag(Optional("en"))
                    }
                    Divider()
                    Toggle("仅未分类", isOn: $store.onlyUncategorized)
                } label: {
                    Label("筛选", systemImage: "line.3.horizontal.decrease.circle")
                        .font(PIHFont.caption)
                }
                .pihToolbarMenu()
                .onChange(of: store.typeFilter) { _, _ in Task { await store.reload() } }
                .onChange(of: store.enabledFilter) { _, _ in Task { await store.reload() } }
                .onChange(of: store.categoryFilter) { _, _ in Task { await store.reload() } }
                .onChange(of: store.languageFilter) { _, _ in Task { await store.reload() } }
                .onChange(of: store.onlyUncategorized) { _, _ in Task { await store.reload() } }

                Button {
                    Task { await store.reload() }
                } label: {
                    Image(systemName: "arrow.clockwise")
                        .font(.system(size: 13, weight: .medium))
                }
                .help("刷新")
                .disabled(store.isLoading)

                Button {
                    editor = SourceDraft()
                } label: {
                    Label("新增", systemImage: "plus")
                        .font(PIHFont.caption)
                }
                .buttonStyle(.borderedProminent)
                .disabled(!model.isDataReady)
            }
        }
    }

    // MARK: - Content

    @ViewBuilder
    private var content: some View {
        if !model.isDataReady {
            EmptyPanel(
                icon: "bolt.horizontal.circle",
                title: "本地服务未就绪",
                message: "信息源管理需要 Sidecar 正常运行。当前状态：\(model.state.title)。",
                actionTitle: "启动 Sidecar",
                action: { model.start() }
            )
        } else if store.isLoading && !store.hasLoaded {
            LoadingStateView(message: "正在加载信息源…")
        } else if let message = store.errorMessage, store.sources.isEmpty {
            EmptyPanel(
                icon: "exclamationmark.triangle",
                title: "加载失败",
                message: message,
                actionTitle: "重试",
                action: { Task { await store.reload() } }
            )
        } else if store.sources.isEmpty {
            EmptyPanel(
                icon: store.searchText.isEmpty ? "dot.radiowaves.left.and.right" : "text.magnifyingglass",
                title: store.searchText.isEmpty ? "还没有信息源" : "没有匹配的信息源",
                message: store.searchText.isEmpty
                    ? "新增第一个信息源，数据会真实写入本地 SQLite。"
                    : "尝试清空搜索词或调整筛选条件。",
                actionTitle: store.searchText.isEmpty ? "新增信息源" : nil,
                action: store.searchText.isEmpty ? { editor = SourceDraft() } : nil
            )
        } else {
            List {
                if let notice = store.collectNotice {
                    Section {
                        NoticeBanner(
                            icon: "checkmark.circle.fill",
                            tint: .green,
                            message: notice,
                            onDismiss: { store.dismissCollectNotice() }
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
                            onDismiss: { store.clearError() }
                        )
                        .listRowSeparator(.hidden)
                    }
                }
                ForEach(store.sources) { source in
                    SourceRow(
                        source: source,
                        store: store,
                        onEdit: { editor = SourceDraft(source: source) },
                        onDelete: { deleting = source },
                        onShowHealth: {
                            healthTarget = SourceHealthTarget(
                                sourceID: source.id,
                                sourceName: source.name
                            )
                        },
                        onShowAdapter: { adapterTarget = source }
                    )
                    .listRowSeparator(.hidden)
                    .listRowInsets(EdgeInsets(top: 3, leading: 14, bottom: 3, trailing: 14))
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
                                Text("加载更多（已显示 \(store.sources.count) / \(store.total)）")
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
            .sheet(item: $healthTarget) { target in
                SourceHealthSheet(target: target, client: model.apiClientForFeatures)
            }
            .sheet(item: $adapterTarget) { source in
                if let client = model.apiClientForFeatures {
                    SourceAdapterEditorView(
                        source: source,
                        client: client,
                        onSaved: { Task { await store.reload() } }
                    )
                }
            }
        }
    }
}

private struct SourceRow: View {
    let source: SourceDTO
    @ObservedObject var store: SourcesStore
    let onEdit: () -> Void
    let onDelete: () -> Void
    let onShowHealth: () -> Void
    let onShowAdapter: () -> Void

    private var isCollecting: Bool {
        store.collectingSourceIDs.contains(source.id)
    }

    var body: some View {
        HStack(alignment: .center, spacing: 14) {
            Image(systemName: "dot.radiowaves.left.and.right")
                .font(.system(size: 14, weight: .medium))
                .foregroundStyle(source.enabled ? Color.accentColor : Color.secondary)
                .frame(width: 34, height: 34)
                .background(
                    Circle().fill((source.enabled ? Color.accentColor : Color.secondary).opacity(0.10))
                )
                .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: 5) {
                HStack(spacing: 6) {
                    Text(source.name)
                        .font(PIHFont.bodySemibold)
                        .lineLimit(1)
                    if let category = source.category {
                        StatusPill(text: category.name, tint: .accentColor)
                    }
                    StatusPill(
                        text: source.enabled ? "已启用" : "已停用",
                        tint: source.enabled ? .green : .gray
                    )
                    if let verification = source.adapterVerification,
                       verification == "selector_drift" || verification == "blocked" {
                        StatusPill(
                            text: verification == "blocked" ? "适配器受阻" : "适配器需检查",
                            tint: .orange
                        )
                    }
                }
                Text(source.url)
                    .font(PIHFont.meta)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .truncationMode(.middle)
                HStack(spacing: 10) {
                    Text(SourceType(rawValue: source.sourceType)?.label ?? source.sourceType)
                    Text("间隔 \(source.fetchIntervalMinutes) 分钟")
                    Text("\(source.articleCount) 篇文章")
                    if let lastSuccess = source.lastSuccessAt {
                        Text("最近成功 \(PIHDateFormat.display(lastSuccess))")
                    } else {
                        Text("尚未采集")
                            .foregroundStyle(.orange)
                    }
                    if let message = source.lastErrorMessage,
                       !message.isEmpty,
                       source.healthStatus != "healthy" {
                        Text("最近错误：\(message)")
                            .foregroundStyle(.orange)
                            .lineLimit(1)
                    }
                }
                .font(PIHFont.meta)
                .foregroundStyle(.tertiary)
            }

            Spacer(minLength: 8)

            HStack(spacing: 4) {
                Button {
                    Task { await store.collect(source) }
                } label: {
                    if isCollecting {
                        ProgressView().controlSize(.small)
                    } else {
                        Image(systemName: "bolt.horizontal")
                    }
                }
                .buttonStyle(.borderless)
                .help("立即采集此来源")
                .accessibilityLabel("立即采集 \(source.name)")
                .disabled(isCollecting)

                Button(action: onShowHealth) {
                    Image(systemName: "waveform.path.ecg")
                }
                .buttonStyle(.borderless)
                .help("查看来源健康日志")
                .accessibilityLabel("查看 \(source.name) 的健康日志")

                if source.sourceType != "rss" && source.sourceType != "atom" {
                    Button(action: onShowAdapter) {
                        Image(systemName: "curlybraces.square")
                    }
                    .buttonStyle(.borderless)
                    .help("配置网页适配器")
                    .accessibilityLabel("配置 \(source.name) 的网页适配器")
                }

                Button(action: onEdit) {
                    Image(systemName: "pencil")
                }
                .buttonStyle(.borderless)
                .help("编辑")
                .accessibilityLabel("编辑 \(source.name)")

                Button(role: .destructive, action: onDelete) {
                    Image(systemName: "trash")
                }
                .buttonStyle(.borderless)
                .help("删除")
                .accessibilityLabel("删除 \(source.name)")
            }
            .font(.system(size: 13))
            .foregroundStyle(.secondary)
            .padding(.horizontal, 4)

            Toggle(
                "启用",
                isOn: Binding(
                    get: { source.enabled },
                    set: { newValue in
                        Task { await store.setEnabled(source, newValue) }
                    }
                )
            )
            .labelsHidden()
            .toggleStyle(.switch)
            .controlSize(.small)
            .disabled(store.isSaving)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .pihRowBackground()
        .contentShape(Rectangle())
        .onTapGesture(count: 2, perform: onEdit)
        .contextMenu {
            Button("立即采集") { Task { await store.collect(source) } }
            Button("健康日志…", action: onShowHealth)
            Button("编辑…", action: onEdit)
            Button("删除…", role: .destructive, action: onDelete)
        }
    }
}
