import type { AxiosInstance } from "axios";
import { describe, expect, it, vi } from "vitest";
import dataProvider from "./dataProvider";

// FilamentDeleteButton (client/src/pages/filaments/filamentDeleteButton.tsx) asks for the
// cascade=true escalation via `meta: { queryParams: { cascade: true } }` on useDelete's mutate --
// the same meta.queryParams convention getList already uses for filters/pagination. That request
// only reaches the server correctly if deleteOne actually turns it into a query-string param; a
// test that only mocks useDelete (as the component test does) can never catch a break here, since
// it never touches this file. This exercises the real deleteOne against a stubbed http client.
function mockHttpClient() {
  return { delete: vi.fn().mockResolvedValue({ data: { message: "Success!" } }) } as unknown as AxiosInstance;
}

describe("dataProvider.deleteOne", () => {
  it("forwards meta.queryParams as the request's query-string params", async () => {
    const httpClient = mockHttpClient();
    const provider = dataProvider("http://api", httpClient);

    await provider.deleteOne({ resource: "filament", id: 5, meta: { queryParams: { cascade: true } } });

    expect(httpClient.delete).toHaveBeenCalledTimes(1);
    const [url, config] = vi.mocked(httpClient.delete).mock.calls[0];
    expect(url).toBe("http://api/filament/5");
    expect(config).toMatchObject({ params: { cascade: true } });
  });

  it("sends no cascade param (or any other) when meta.queryParams is absent", async () => {
    const httpClient = mockHttpClient();
    const provider = dataProvider("http://api", httpClient);

    await provider.deleteOne({ resource: "filament", id: 5 });

    const [, config] = vi.mocked(httpClient.delete).mock.calls[0];
    expect(config).toMatchObject({ params: {} });
  });
});
