import SwiftUI
import ZaolangKit

/// 一个音色：名称、来源、模型 · 音色、属性、绑定造型；可播放试听、设为默认、生成试听（先报价确认）。
struct VoiceRow: View {
    let voice: CharacterVoiceView
    let lookNames: [String]
    let pending: Bool
    let player: VoicePlayer
    let viewModel: CharacterDetailViewModel

    @State private var quote: VoicePreviewResponse?

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 6) {
                Text(voice.name).font(.subheadline.weight(.semibold)).foregroundStyle(Color.zl.text)
                if voice.isDefault {
                    Text(L10n.t("assetGraph.defaultBadge")).font(.caption2.weight(.medium)).foregroundStyle(Color.zl.primary)
                }
                Spacer(minLength: 0)
                if let url = voice.preview?.url {
                    Button { player.toggle(url) } label: {
                        Image(systemName: player.playingURL == url ? "stop.circle.fill" : "play.circle.fill")
                            .font(.title2)
                            .frame(minWidth: 44, minHeight: 44)
                    }
                    .accessibilityLabel(L10n.t(player.playingURL == url ? "assetGraph.stop" : "assetGraph.play"))
                }
            }
            Text(summary).font(.caption).foregroundStyle(Color.zl.textMuted)
            if let description = voice.description, !description.isEmpty {
                Text(description).font(.caption).foregroundStyle(Color.zl.textMuted)
            }
            if !lookNames.isEmpty {
                Text(L10n.t("iosCharacters.boundLooks", ["names": lookNames.joined(separator: "、")]))
                    .font(.caption)
                    .foregroundStyle(Color.zl.textMuted)
            }
            HStack(spacing: 8) {
                if !voice.isDefault {
                    Button(L10n.t("assetGraph.makeDefaultVoice")) {
                        Task { await viewModel.makeDefault(voice) }
                    }
                }
                Button {
                    Task { quote = await viewModel.previewQuote(voice) }
                } label: {
                    if pending || viewModel.busyVoiceID == voice.id {
                        HStack(spacing: 6) { ProgressView(); Text(L10n.t("assetGraph.previewGenerating")) }
                    } else {
                        Text(L10n.t("assetGraph.generatePreview"))
                    }
                }
                .disabled(pending || viewModel.busyVoiceID != nil)
            }
            .buttonStyle(.bordered)
            .controlSize(.small)
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.zl.surface)
        .zlCornerRadius(ZLRadius.md)
        .confirmationDialog(
            L10n.t("assetGraph.generatePreview"),
            isPresented: Binding(get: { quote != nil }, set: { if !$0 { quote = nil } }),
            titleVisibility: .visible,
            presenting: quote
        ) { quote in
            Button(L10n.t("assetGraph.generatePreview")) {
                Task { await viewModel.generatePreview(voice) }
            }
            .disabled(!quote.sufficient)
        } message: { quote in
            Text(L10n.t("iosCharacters.previewConfirm", ["credits": quote.credits, "available": quote.availableCredits]))
        }
    }

    private var summary: String {
        var parts = [L10n.t(voice.source == "clone" ? "assetGraph.voiceClone" : "assetGraph.voicePreset")]
        if let model = voice.model, let name = voice.voice { parts.append("\(model) · \(name)") }
        if let age = voice.attributes?.ageStage { parts.append(L10n.t("assetVariants.ageStage.\(age)")) }
        if let use = voice.attributes?.use { parts.append(L10n.t("assetGraph.voiceUse.\(use)")) }
        if let emotion = voice.attributes?.emotion { parts.append(emotion) }
        if let speed = voice.params?.speed { parts.append("×\(String(format: "%.2f", speed))") }
        return parts.joined(separator: " · ")
    }
}
