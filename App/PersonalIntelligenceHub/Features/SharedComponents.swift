import SwiftUI

struct ErrorBanner: View {
    let message: String
    let requestID: String?
    let onRetry: (() -> Void)?
    let onDismiss: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: PIHSpacing.control) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(PIHFont.bannerIconSemibold)
                .foregroundStyle(.orange)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 4) {
                Text(message)
                    .font(PIHFont.caption)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
                if let requestID {
                    Text("请求 ID：\(requestID)")
                        .font(PIHFont.metaMono)
                        .foregroundStyle(.secondary)
                        .textSelection(.enabled)
                }
            }
            Spacer(minLength: 8)
            if let onRetry {
                Button("重试", action: onRetry)
                    .buttonStyle(.link)
                    .font(PIHFont.captionMedium)
            }
            Button {
                onDismiss()
            } label: {
                Image(systemName: "xmark")
                    .font(PIHFont.iconSmall)
            }
            .buttonStyle(.plain)
            .foregroundStyle(.secondary)
            .accessibilityLabel("关闭错误提示")
        }
        .padding(14)
        .background(
            RoundedRectangle(cornerRadius: PIHRadius.control, style: .continuous)
                .fill(Color.orange.opacity(0.09))
        )
        .overlay(
            RoundedRectangle(cornerRadius: PIHRadius.control, style: .continuous)
                .strokeBorder(Color.orange.opacity(0.25), lineWidth: 1)
        )
    }
}

struct EmptyPanel: View {
    let icon: String
    let title: String
    let message: String
    let actionTitle: String?
    let action: (() -> Void)?

    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: icon)
                .font(PIHFont.iconXL)
                .foregroundStyle(.secondary)
                .frame(width: 72, height: 72)
                .background(
                    Circle().fill(Color.secondary.opacity(0.08))
                )
                .accessibilityHidden(true)
            VStack(spacing: 6) {
                Text(title)
                    .font(PIHFont.subsectionTitle)
                Text(message)
                    .font(PIHFont.caption)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: 420)
            }
            if let actionTitle, let action {
                Button(actionTitle, action: action)
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
                    .padding(.top, 2)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(36)
    }
}

struct StatusPill: View {
    let text: String
    let tint: Color

    var body: some View {
        Text(text)
            .font(PIHFont.meta.weight(.medium))
            .lineLimit(1)
            .padding(.horizontal, 9)
            .padding(.vertical, 4)
            .foregroundStyle(tint)
            .background(Capsule().fill(tint.opacity(0.13)))
    }
}

struct FieldErrorText: View {
    let message: String?

    var body: some View {
        if let message {
            Text(message)
                .font(PIHFont.meta)
                .foregroundStyle(.red)
        }
    }
}

/// 带清空按钮的搜索框，供文章与任务列表复用。
struct SearchField: View {
    let placeholder: String
    @Binding var text: String
    var width: CGFloat = 220

    var body: some View {
        HStack(spacing: 7) {
            Image(systemName: "magnifyingglass")
                .font(PIHFont.metaMedium)
                .foregroundStyle(.secondary)
                .accessibilityHidden(true)
            TextField(placeholder, text: $text)
                .textFieldStyle(.plain)
                .font(PIHFont.caption)
                .frame(width: width)
            if !text.isEmpty {
                Button {
                    text = ""
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .font(PIHFont.meta)
                        .foregroundStyle(.secondary)
                }
                .buttonStyle(.plain)
                .accessibilityLabel("清空搜索")
            }
        }
        .padding(.horizontal, 10)
        .frame(height: 30)
        .background(
            RoundedRectangle(cornerRadius: PIHRadius.control, style: .continuous)
                .fill(PIHColor.surface)
        )
        .overlay(
            RoundedRectangle(cornerRadius: PIHRadius.control, style: .continuous)
                .strokeBorder(PIHColor.hairline, lineWidth: 1)
        )
    }
}

/// 成功/提示类横幅。只用于真实操作结果，不伪造进度。
struct NoticeBanner: View {
    let icon: String
    let tint: Color
    let message: String
    let onDismiss: (() -> Void)?

    var body: some View {
        HStack(alignment: .top, spacing: PIHSpacing.control) {
            Image(systemName: icon)
                .font(PIHFont.bannerIconSemibold)
                .foregroundStyle(tint)
                .accessibilityHidden(true)
            Text(message)
                .font(PIHFont.caption)
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
            Spacer(minLength: 8)
            if let onDismiss {
                Button(action: onDismiss) {
                    Image(systemName: "xmark")
                        .font(PIHFont.iconSmall)
                }
                .buttonStyle(.plain)
                .foregroundStyle(.secondary)
                .accessibilityLabel("关闭提示")
            }
        }
        .padding(14)
        .background(
            RoundedRectangle(cornerRadius: PIHRadius.control, style: .continuous)
                .fill(tint.opacity(0.09))
        )
        .overlay(
            RoundedRectangle(cornerRadius: PIHRadius.control, style: .continuous)
                .strokeBorder(tint.opacity(0.22), lineWidth: 1)
        )
    }
}

extension CollectionJobStatus {
    var tint: Color {
        switch self {
        case .pending: return .secondary
        case .running: return .blue
        case .succeeded: return .green
        case .partiallySucceeded: return .orange
        case .failed: return .red
        case .cancelled: return .gray
        }
    }
}

extension CollectionJobItemStatus {
    var tint: Color {
        switch self {
        case .pending: return .secondary
        case .running: return .blue
        case .succeeded: return .green
        case .failed: return .red
        case .skipped: return .gray
        case .cancelled: return .gray
        }
    }
}

extension SourceHealthStatus {
    var tint: Color {
        switch self {
        case .healthy: return .green
        case .degraded: return .orange
        case .failing: return .red
        }
    }
}
