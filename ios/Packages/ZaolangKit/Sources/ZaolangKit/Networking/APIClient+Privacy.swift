import Foundation

/// 数据导出与账号注销申请。都是"排队等人工审批"，不是即时执行——注销尤其不可逆，
/// 界面层必须在提交前有一道二次确认。
public extension APIClient {
    func createDataRequest(_ payload: DataRequestCreateRequest) async throws -> MyDataRequestResponse {
        try await send(.post("/v1/me/data-requests", body: payload))
    }

    func listDataRequests() async throws -> Page<MyDataRequestResponse> {
        try await send(.get("/v1/me/data-requests"))
    }
}
