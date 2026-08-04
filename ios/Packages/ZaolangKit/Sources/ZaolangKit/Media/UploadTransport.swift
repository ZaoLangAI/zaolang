import CryptoKit
import Foundation

/// 上传第二步（把文件真正传到对象存储）不走 `APIClient`：目标是预签名 URL，
/// 不需要也不能带 Bearer/幂等键，签名已经把校验和、大小、MIME 全绑死在 URL 参数里。
public struct UploadTransport: Sendable {
    private let session: URLSession

    public init(session: URLSession) {
        self.session = session
    }

    /// `requiredHeaders` 原样来自 `UploadPresignResponse`——签名校验这些头，多一个少一个都会 403。
    public func put(data: Data, to uploadURLString: String, requiredHeaders: [String: String]) async throws {
        guard let url = URL(string: uploadURLString) else {
            throw ApiError.unexpectedResponse(status: 0)
        }
        var request = URLRequest(url: url)
        request.httpMethod = "PUT"
        for (field, value) in requiredHeaders {
            request.setValue(value, forHTTPHeaderField: field)
        }

        let response: URLResponse
        do {
            (_, response) = try await session.upload(for: request, from: data)
        } catch let urlError as URLError {
            throw ApiError.transport(urlError)
        }
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw ApiError.unexpectedResponse(status: (response as? HTTPURLResponse)?.statusCode ?? 0)
        }
    }

    /// 预签名请求要求上传前算好整份内容的 SHA-256（十六进制小写），把签名绑定到这份具体内容。
    public static func sha256Hex(of data: Data) -> String {
        let digest = SHA256.hash(data: data)
        return digest.map { String(format: "%02x", $0) }.joined()
    }
}
