import SwiftUI
import UIKit
import ZaolangKit

/// 积分账单，只读展示——不接 `POST /v1/credits/checkout`（产品决策：不接 StoreKit，
/// 余额不足或想购买时引导去网页版，见 `zaolang-ios-client` skill 的路线图）。
struct BillingView: View {
    @Environment(AppEnvironment.self) private var environment
    @State private var viewModel: BillingViewModel?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                balanceSection
                packagesSection
                ledgerSection
            }
            .padding(16)
        }
        .navigationTitle(L10n.t("billingPage.title"))
        .navigationBarTitleDisplayMode(.inline)
        .task {
            if viewModel == nil {
                viewModel = BillingViewModel(apiClient: environment.apiClient)
            }
            await viewModel?.load()
        }
        .refreshable { await viewModel?.load() }
    }

    @ViewBuilder
    private var balanceSection: some View {
        switch viewModel?.balanceState ?? .loading {
        case .loading:
            RoundedRectangle.zl(ZLRadius.md).fill(Color.zl.skeleton).zlSkeletonPulse().frame(height: 96)
        case .failed(let error):
            ErrorStateView(error: error) { Task { await viewModel?.load() } }
        case .empty:
            EmptyView()
        case .loaded(let balance):
            HStack(spacing: 24) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("\(balance.available)").font(.title.weight(.bold))
                    Text(L10n.t("billingPage.available")).font(.caption).foregroundStyle(Color.zl.textMuted)
                }
                VStack(alignment: .leading, spacing: 2) {
                    Text("\(balance.reserved)").font(.title2.weight(.semibold)).foregroundStyle(Color.zl.textMuted)
                    Text(L10n.t("billingPage.reserved")).font(.caption).foregroundStyle(Color.zl.textMuted)
                }
                Spacer()
            }
            .padding(16)
            .background(Color.zl.surface)
            .zlCornerRadius(ZLRadius.md)
        }
    }

    @ViewBuilder
    private var packagesSection: some View {
        if case .loaded(let packages) = viewModel?.packagesState ?? .loading, !packages.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                Text(L10n.t("billingPage.packages")).zlEyebrow()
                Text(L10n.t("billingPage.packagesHint")).font(.footnote).foregroundStyle(Color.zl.textMuted)
                ForEach(packages) { package in
                    packageRow(package)
                }
            }
        }
    }

    private func packageRow(_ package: CreditPackageResponse) -> some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text(L10n.t("billingPage.packageCredits", ["count": package.credits]))
                    .font(.subheadline.weight(.medium))
                if package.bonusCredits > 0 {
                    Text(L10n.t("billingPage.bonus", ["count": package.bonusCredits]))
                        .font(.caption)
                        .foregroundStyle(Color.zl.amber)
                }
            }
            Spacer()
            Button {
                openWebCheckout()
            } label: {
                Text(L10n.t("billingPage.buy"))
            }
            .buttonStyle(.bordered)
        }
        .padding(12)
        .background(Color.zl.surface)
        .zlCornerRadius(ZLRadius.md)
    }

    private func openWebCheckout() {
        guard let url = URL(string: "\(AppConfig.webBaseURLString)/billing") else { return }
        UIApplication.shared.open(url)
    }

    @ViewBuilder
    private var ledgerSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(L10n.t("billingPage.ledger")).zlEyebrow()
            switch viewModel?.ledgerState ?? .loading {
            case .loading:
                ForEach(0..<4, id: \.self) { _ in
                    RoundedRectangle.zl(ZLRadius.sm).fill(Color.zl.skeleton).zlSkeletonPulse().frame(height: 48)
                }
            case .empty:
                Text(L10n.t("billingPage.ledgerEmpty")).font(.footnote).foregroundStyle(Color.zl.textMuted)
            case .failed(let error):
                ErrorStateView(error: error) { Task { await viewModel?.load() } }
            case .loaded(let entries):
                ForEach(entries) { entry in
                    ledgerRow(entry)
                }
            }
        }
    }

    private func ledgerRow(_ entry: LedgerEntryResponse) -> some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text(L10n.t(entry.type.value?.labelKey ?? "billingPage.typeAdjustment")).font(.subheadline)
                Text(entry.createdAt.formatted(date: .abbreviated, time: .shortened))
                    .font(.caption2)
                    .foregroundStyle(Color.zl.textMuted)
            }
            Spacer()
            Text(entry.amount > 0 ? "+\(entry.amount)" : "\(entry.amount)")
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(entry.amount > 0 ? Color.zl.success : Color.zl.text)
            Text("· \(entry.balanceAfter)")
                .font(.caption)
                .foregroundStyle(Color.zl.textMuted)
        }
        .padding(.vertical, 6)
    }
}
