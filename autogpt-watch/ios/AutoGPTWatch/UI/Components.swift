import SwiftUI
import AutoGPTCore

/// Interruptor principal: un botón circular grande.
struct PowerToggle: View {
    let isOn: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            ZStack {
                Circle()
                    .fill(isOn ? Theme.accentGradient : Theme.offGradient)
                    .shadow(color: isOn ? Theme.accent.opacity(0.55) : .black.opacity(0.5), radius: isOn ? 40 : 14)
                Circle()
                    .strokeBorder(Color.white.opacity(isOn ? 0.35 : 0.12), lineWidth: 1.5)
                VStack(spacing: 10) {
                    Image(systemName: "power")
                        .font(.system(size: 56, weight: .semibold))
                    Text(isOn ? "ACTIVO" : "INACTIVO")
                        .font(.system(size: 14, weight: .heavy, design: .rounded))
                        .tracking(2.5)
                }
                .foregroundStyle(isOn ? Color.black.opacity(0.85) : Color.white.opacity(0.85))
            }
            .frame(width: 196, height: 196)
            .contentShape(Circle())
        }
        .buttonStyle(.plain)
        .sensoryFeedback(.impact(weight: .medium), trigger: isOn)
        .animation(.spring(response: 0.4, dampingFraction: 0.75), value: isOn)
        .accessibilityLabel(isOn ? "Desactivar modo automático" : "Activar modo automático")
    }
}

struct StatusPill: View {
    let status: AppStatus

    var body: some View {
        HStack(spacing: 8) {
            Circle().fill(status.color).frame(width: 9, height: 9)
                .shadow(color: status.color.opacity(0.8), radius: 4)
            Text(status.label)
                .font(.system(size: 15, weight: .semibold, design: .rounded))
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 8)
        .background(Capsule().fill(status.color.opacity(0.14)))
        .overlay(Capsule().strokeBorder(status.color.opacity(0.35), lineWidth: 1))
    }
}

struct StatCard: View {
    let value: Int
    let label: String
    let systemImage: String

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Image(systemName: systemImage)
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(Theme.accent)
            Text("\(value)")
                .font(.system(size: 28, weight: .bold, design: .rounded))
                .contentTransition(.numericText())
            Text(label)
                .font(.caption)
                .foregroundStyle(Theme.secondaryText)
                .lineLimit(2)
                .minimumScaleFactor(0.8)
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 18, style: .continuous).fill(Theme.card))
        .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).strokeBorder(Theme.cardBorder, lineWidth: 1))
    }
}

struct SectionHeader: View {
    let title: String
    var trailing: AnyView?

    init(_ title: String, trailing: AnyView? = nil) {
        self.title = title
        self.trailing = trailing
    }

    var body: some View {
        HStack {
            Text(title.uppercased())
                .font(.system(size: 13, weight: .bold, design: .rounded))
                .tracking(1.2)
                .foregroundStyle(Theme.secondaryText)
            Spacer()
            if let trailing { trailing }
        }
        .padding(.horizontal, 4)
    }
}

struct PhaseBadge: View {
    let phase: JobPhase

    private var color: Color {
        switch phase {
        case .saved: return Theme.accent
        case .failed: return Theme.danger
        case .retryWait: return Theme.warning
        case .noAnswer: return .gray
        default: return Theme.processing
        }
    }

    var body: some View {
        Text(phase.displayName)
            .font(.system(size: 11, weight: .semibold))
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(Capsule().fill(color.opacity(0.16)))
            .foregroundStyle(color)
    }
}

struct JobRow: View {
    let job: LocalJob
    var onRetry: (() -> Void)?
    var onDiscard: (() -> Void)?

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline) {
                Text(job.displayTitle)
                    .font(.system(size: 16, weight: .semibold))
                    .lineLimit(2)
                Spacer(minLength: 8)
                PhaseBadge(phase: job.phase)
            }
            HStack(spacing: 12) {
                Label(job.createdAt.formatted(date: .abbreviated, time: .shortened), systemImage: "clock")
                if job.photoCount > 0 {
                    Label("\(job.photoCount)", systemImage: "camera")
                }
                if !job.savedAssetIDs.isEmpty {
                    Label("\(job.savedAssetIDs.count) en Favoritos", systemImage: "heart.fill")
                }
            }
            .font(.caption)
            .foregroundStyle(Theme.secondaryText)
            if let error = job.lastError, !error.isEmpty {
                Text(error)
                    .font(.caption)
                    .foregroundStyle(job.phase == .failed ? Theme.danger : Theme.warning)
            }
            if onRetry != nil || onDiscard != nil {
                HStack {
                    if let onRetry {
                        Button("Reintentar", systemImage: "arrow.clockwise", action: onRetry)
                    }
                    if let onDiscard {
                        Button("Descartar", systemImage: "trash", role: .destructive, action: onDiscard)
                    }
                }
                .buttonStyle(.bordered)
                .controlSize(.small)
            }
        }
        .card()
    }
}
