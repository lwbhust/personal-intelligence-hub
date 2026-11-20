import SwiftUI

struct CategoriesScreen: View {
    @ObservedObject var model: SidecarViewModel
    @ObservedObject var store: SourcesStore

    @State private var editor: CategoryDraft?
    @State private var deleting: SourceCategoryDTO?

    var body: some View {
        VStack(spacing: 0) {
            toolbar
            Divider().overlay(PIHColor.hairline)
            content
        }
        .frame(minWidth: 620, minHeight: 480)
        .background(PIHColor.canvas)
        .sheet(item: $editor) { draft in
            CategoryEditorView(store: store, draft: draft)
        }
        .alert(
            "删除分类？",
            isPresented: Binding(
                get: { deleting != nil },
                set: { if !$0 { deleting = nil } }
            ),
            presenting: deleting
        ) { category in
            Button("删除", role: .destructive) {
                Task {
                    await store.deleteCategory(category)
                    deleting = nil
                }
            }
            Button("取消", role: .cancel) { deleting = nil }
        } message: { category in
            Text("「\(category.name)」将被软删除。若仍有信息源引用，会提示“该分类仍被信息源引用”。")
        }
    }

    private var toolbar: some View {
        PIHPageToolbar {
            PageHeader(
                "分类",
                subtitle: "共 \(store.categories.count) 个 · 用于给信息源分组"
            ) {
                HStack(spacing: PIHSpacing.control) {
                    Button {
                        Task { await store.reload() }
                    } label: {
                        Image(systemName: "arrow.clockwise")
                            .font(.system(size: 13, weight: .medium))
                    }
                    .help("刷新")
                    .disabled(store.isLoading)
                    Button {
                        editor = CategoryDraft()
                    } label: {
                        Label("新增分类", systemImage: "plus")
                            .font(PIHFont.caption)
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(!model.isDataReady)
                }
            }
        }
    }

    @ViewBuilder
    private var content: some View {
        if !model.isDataReady {
            EmptyPanel(
                icon: "bolt.horizontal.circle",
                title: "本地服务未就绪",
                message: "分类管理需要 Sidecar 正常运行。当前状态：\(model.state.title)。",
                actionTitle: "启动 Sidecar",
                action: { model.start() }
            )
        } else if let message = store.errorMessage, store.categories.isEmpty {
            EmptyPanel(
                icon: "exclamationmark.triangle",
                title: "加载失败",
                message: message,
                actionTitle: "重试",
                action: { Task { await store.reload() } }
            )
        } else if store.categories.isEmpty && store.hasLoaded {
            EmptyPanel(
                icon: "folder",
                title: "还没有分类",
                message: "分类用于给信息源分组；也可以先把分类留空。",
                actionTitle: "新增分类",
                action: { editor = CategoryDraft() }
            )
        } else {
            List {
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
                ForEach(store.categories) { category in
                    HStack(spacing: 14) {
                        Image(systemName: "folder.fill")
                            .font(.system(size: 14, weight: .medium))
                            .foregroundStyle(.tint)
                            .frame(width: 34, height: 34)
                            .background(Circle().fill(Color.accentColor.opacity(0.10)))
                            .accessibilityHidden(true)
                        VStack(alignment: .leading, spacing: 4) {
                            Text(category.name)
                                .font(PIHFont.bodySemibold)
                            if let description = category.description, !description.isEmpty {
                                Text(description)
                                    .font(PIHFont.caption)
                                    .foregroundStyle(.secondary)
                                    .lineLimit(2)
                            }
                        }
                        Spacer()
                        Text("\(category.sourceCount) 个信息源")
                            .font(PIHFont.meta)
                            .foregroundStyle(.secondary)
                        HStack(spacing: 4) {
                            Button {
                                editor = CategoryDraft(category: category)
                            } label: {
                                Image(systemName: "pencil")
                            }
                            .buttonStyle(.borderless)
                            .help("编辑")
                            .accessibilityLabel("编辑 \(category.name)")
                            Button(role: .destructive) {
                                deleting = category
                            } label: {
                                Image(systemName: "trash")
                            }
                            .buttonStyle(.borderless)
                            .help("删除")
                            .accessibilityLabel("删除 \(category.name)")
                        }
                        .font(.system(size: 13))
                        .foregroundStyle(.secondary)
                    }
                    .padding(.horizontal, 12)
                    .padding(.vertical, 10)
                    .pihRowBackground()
                    .contentShape(Rectangle())
                    .onTapGesture(count: 2) {
                        editor = CategoryDraft(category: category)
                    }
                    .contextMenu {
                        Button("编辑…") { editor = CategoryDraft(category: category) }
                        Button("删除…", role: .destructive) { deleting = category }
                    }
                    .listRowSeparator(.hidden)
                    .listRowInsets(EdgeInsets(top: 3, leading: 14, bottom: 3, trailing: 14))
                }
            }
            .listStyle(.inset)
            .scrollContentBackground(.hidden)
            .background(PIHColor.canvas)
        }
    }
}

struct CategoryEditorView: View {
    @ObservedObject var store: SourcesStore
    @State private var draft: CategoryDraft
    @Environment(\.dismiss) private var dismiss

    init(store: SourcesStore, draft: CategoryDraft) {
        self.store = store
        _draft = State(initialValue: draft)
    }

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text(draft.isEditing ? "编辑分类" : "新增分类")
                    .font(PIHFont.subsectionTitle)
                Spacer()
            }
            .padding(.horizontal, 24)
            .padding(.vertical, 18)
            Divider()
            VStack(alignment: .leading, spacing: 16) {
                if let message = store.errorMessage {
                    ErrorBanner(
                        message: message,
                        requestID: store.errorRequestID,
                        onRetry: nil,
                        onDismiss: { store.clearError() }
                    )
                }
                VStack(alignment: .leading, spacing: 6) {
                    Text("名称")
                        .font(PIHFont.caption)
                        .foregroundStyle(.secondary)
                    TextField("例如：AI 与科技", text: $draft.name)
                    FieldErrorText(message: store.fieldErrors["name"])
                }
                VStack(alignment: .leading, spacing: 6) {
                    Text("描述（可选）")
                        .font(PIHFont.caption)
                        .foregroundStyle(.secondary)
                    TextField("分类说明", text: $draft.description, axis: .vertical)
                        .lineLimit(2...4)
                    FieldErrorText(message: store.fieldErrors["description"])
                }
                VStack(alignment: .leading, spacing: 6) {
                    Text("排序（-1000…1000）")
                        .font(PIHFont.caption)
                        .foregroundStyle(.secondary)
                    TextField("0", value: $draft.sortOrder, format: .number)
                        .frame(width: 120)
                    FieldErrorText(message: store.fieldErrors["sort_order"])
                }
            }
            .padding(24)
            Divider()
            HStack {
                Spacer()
                Button("取消") { dismiss() }
                    .keyboardShortcut(.cancelAction)
                Button {
                    Task {
                        if await store.saveCategory(draft) {
                            dismiss()
                        }
                    }
                } label: {
                    if store.isSaving {
                        ProgressView().controlSize(.small)
                    } else {
                        Text("保存")
                    }
                }
                .buttonStyle(.borderedProminent)
                .keyboardShortcut(.defaultAction)
                .disabled(store.isSaving)
            }
            .padding(.horizontal, 24)
            .padding(.vertical, 14)
        }
        .frame(width: 480, height: 400)
    }
}
