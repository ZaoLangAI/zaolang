import SwiftUI
import ZaolangKit

/// One slot of the board: its approved image and candidates (each can be 定稿).
/// The primary slot (定妆照 / 主图) offers a quick generate — price, confirm,
/// submit, then the sheet closes and the board shows it running; every other
/// slot links to the web workspace.
struct SlotSheet: View {
    let variantID: String
    let slotID: String
    let viewModel: AssetDetailViewModel

    @Environment(\.dismiss) private var dismiss
    @Environment(\.openURL) private var openURL
    @State private var tier: QualityTier = .standard
    @State private var quote: QuoteResponse?
    @State private var quoteError: String?
    @State private var confirming = false

    private var variant: AssetVariantView? {
        viewModel.graph?.variants.first { $0.id == variantID }
    }

    private var state: AssetSlots.SlotState? {
        guard let graph = viewModel.graph, let variant else { return nil }
        return AssetSlots.slotStates(
            viewModel.kind, variant: variant, allEntries: graph.variants.flatMap(\.entries), pending: graph.pending
        ).first { $0.slot.id == slotID }
    }

    private var isGenerating: Bool {
        viewModel.generatingSlot == AssetDetailViewModel.slotKey(variantID: variantID, slotID: slotID)
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                if let state, let variant {
                    VStack(alignment: .leading, spacing: 16) {
                        statusRow(state)
                        if let approved = state.approved {
                            RemoteImage(url: approved.url.flatMap(URL.init(string:)), aspectRatio: 1, contentMode: .fit)
                                .frame(maxWidth: .infinity)
                                .zlCornerRadius(ZLRadius.md)
                        }
                        if !state.candidates.isEmpty { candidates(state) }
                        if state.slot.isPrimary {
                            quickGenerate(state, variant: variant)
                        } else {
                            webContinue
                        }
                    }
                    .padding(16)
                }
            }
            .navigationTitle(L10n.t("assetWorkspace.slot.\(slotID)"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button(L10n.t("actions.close")) { dismiss() }
                }
            }
        }
    }

    private func statusRow(_ state: AssetSlots.SlotState) -> some View {
        let status: AssetSlots.Status = isGenerating ? .pending : state.status
        return HStack(spacing: 8) {
            if status == .pending { ProgressView().controlSize(.small) }
            Text(L10n.t("assetWorkspace.status.\(status.rawValue)"))
                .font(.subheadline.weight(.medium))
                .foregroundStyle(status == .approved ? Color.zl.success : Color.zl.textMuted)
            if !state.slot.required {
                Text(L10n.t("assetWorkspace.optional")).font(.caption).foregroundStyle(Color.zl.textMuted)
            }
        }
    }

    private func candidates(_ state: AssetSlots.SlotState) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(L10n.t("assetWorkspace.candidatesHint", ["count": state.candidates.count]))
                .font(.caption)
                .foregroundStyle(Color.zl.textMuted)
            LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 8), count: 2), spacing: 12) {
                ForEach(state.candidates) { entry in
                    VStack(spacing: 6) {
                        RemoteImage(url: entry.url.flatMap(URL.init(string:)), aspectRatio: 1)
                            .zlCornerRadius(ZLRadius.sm)
                            .accessibilityLabel(L10n.t("assetVariants.candidate"))
                        Button {
                            Task {
                                await viewModel.approve(entry)
                                dismiss()
                            }
                        } label: {
                            Text(L10n.t("assetWorkspace.approve")).frame(maxWidth: .infinity, minHeight: 32)
                        }
                        .buttonStyle(.bordered)
                        .disabled(viewModel.approvingID != nil)
                    }
                }
            }
        }
    }

    private func quickGenerate(_ state: AssetSlots.SlotState, variant: AssetVariantView) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(L10n.t("assetWorkspace.quality")).font(.subheadline.weight(.semibold))
            Picker(L10n.t("assetWorkspace.quality"), selection: $tier) {
                ForEach(QualityTier.allCases, id: \.self) { tier in
                    Text(L10n.t("assetWorkspace.tier.\(tier.rawValue)")).tag(tier)
                }
            }
            .pickerStyle(.segmented)
            Button { confirming = true } label: {
                Group {
                    if let quote {
                        Text(L10n.t("assetWorkspace.generateFor", ["credits": quote.credits]))
                    } else {
                        Text(L10n.t("assetWorkspace.generatePricing"))
                    }
                }
                .font(.body.weight(.semibold))
                .frame(maxWidth: .infinity, minHeight: 32)
            }
            .buttonStyle(.borderedProminent)
            .disabled(quote?.sufficient != true || isGenerating || state.status == .pending || viewModel.generatingSlot != nil)
            if let quote, !quote.sufficient {
                Text(L10n.t("assetWorkspace.insufficient", ["available": quote.availableCredits]))
                    .font(.caption)
                    .foregroundStyle(Color.zl.danger)
            }
            if let quoteError {
                Text(quoteError).font(.caption).foregroundStyle(Color.zl.danger)
            }
        }
        .task(id: tier) {
            quote = nil
            quoteError = nil
            switch await viewModel.quotePrimary(tier: tier) {
            case .success(let priced): quote = priced
            case .failure(let error): quoteError = error.fallbackMessage
            }
        }
        .confirmationDialog(
            L10n.t("assetWorkspace.slot.\(slotID)"),
            isPresented: $confirming,
            titleVisibility: .visible,
            presenting: quote
        ) { quote in
            Button(L10n.t("assetWorkspace.generateFor", ["credits": quote.credits])) {
                let tier = tier
                Task { await viewModel.generate(state.slot, variant: variant, tier: tier, quote: quote) }
                dismiss()
            }
        } message: { quote in
            Text(L10n.t("iosAssets.generateConfirm", ["credits": quote.credits, "available": quote.availableCredits]))
        }
    }

    private var webContinue: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(L10n.t("iosAssets.continueOnWebHint")).font(.caption).foregroundStyle(Color.zl.textMuted)
            Button {
                if let url = AssetSlots.webURL(viewModel.kind, cardID: viewModel.cardID, variantID: variantID) {
                    openURL(url)
                }
            } label: {
                Label(L10n.t("iosAssets.continueOnWeb"), systemImage: "arrow.up.right.square")
            }
            .buttonStyle(.bordered)
        }
    }
}
