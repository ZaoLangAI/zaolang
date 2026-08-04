import Foundation

/// 只读展示：余额、账本、积分包目录。**不包含 `checkout`**——产品决策是不接 StoreKit，
/// 余额不足时引导去网页版购买，详见 `zaolang-ios-client` skill 的路线图。
public extension APIClient {
    func creditBalance() async throws -> CreditBalanceResponse {
        try await send(.get("/v1/credits/balance"))
    }

    func creditLedger(cursor: String? = nil, limit: Int = 20) async throws -> Page<LedgerEntryResponse> {
        var query = [URLQueryItem(name: "limit", value: String(limit))]
        if let cursor { query.append(URLQueryItem(name: "cursor", value: cursor)) }
        return try await send(.get("/v1/credits/ledger", query: query))
    }

    func creditPackages() async throws -> Page<CreditPackageResponse> {
        try await send(.get("/v1/credits/packages"))
    }
}
