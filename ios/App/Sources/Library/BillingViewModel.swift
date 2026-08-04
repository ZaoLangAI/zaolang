import Observation
import ZaolangKit

@MainActor
@Observable
final class BillingViewModel {
    private let apiClient: APIClient

    private(set) var balanceState: LoadableState<CreditBalanceResponse> = .loading
    private(set) var ledgerState: LoadableState<[LedgerEntryResponse]> = .loading
    private(set) var packagesState: LoadableState<[CreditPackageResponse]> = .loading

    init(apiClient: APIClient) {
        self.apiClient = apiClient
    }

    func load() async {
        async let balance: () = loadBalance()
        async let ledger: () = loadLedger()
        async let packages: () = loadPackages()
        _ = await (balance, ledger, packages)
    }

    private func loadBalance() async {
        do {
            balanceState = .loaded(try await apiClient.creditBalance())
        } catch let error as ApiError {
            balanceState = .failed(error)
        } catch {
            balanceState = .failed(.unexpectedResponse(status: 0))
        }
    }

    private func loadLedger() async {
        do {
            let page = try await apiClient.creditLedger(limit: 30)
            ledgerState = page.items.isEmpty ? .empty : .loaded(page.items)
        } catch let error as ApiError {
            ledgerState = .failed(error)
        } catch {
            ledgerState = .failed(.unexpectedResponse(status: 0))
        }
    }

    private func loadPackages() async {
        do {
            let page = try await apiClient.creditPackages()
            packagesState = page.items.isEmpty ? .empty : .loaded(page.items)
        } catch let error as ApiError {
            packagesState = .failed(error)
        } catch {
            packagesState = .failed(.unexpectedResponse(status: 0))
        }
    }
}

extension LedgerEntryType {
    var labelKey: String {
        switch self {
        case .grant: "billingPage.typeGrant"
        case .purchase: "billingPage.typePurchase"
        case .reserve: "billingPage.typeReserve"
        case .capture: "billingPage.typeCapture"
        case .release: "billingPage.typeRelease"
        case .refund: "billingPage.typeRefund"
        case .adjustment: "billingPage.typeAdjustment"
        case .royaltyIn: "billingPage.typeRoyaltyIn"
        case .royaltyOut: "billingPage.typeRoyaltyOut"
        }
    }
}
