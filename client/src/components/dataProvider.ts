import { DataProvider } from "@refinedev/core";
import { axiosInstance } from "@refinedev/simple-rest";
import { AxiosInstance } from "axios";
import { stringify } from "query-string";
import { parseJsonWithBigIntIds } from "../utils/bigintJson";
import { getCustomFieldFilters, serializeFilterValues } from "../utils/filtering";
import { isCustomField } from "../utils/queryFields";

// Parse responses with a big-int-aware JSON parser so CockroachDB's oversized primary keys survive
// instead of being rounded by the default JSON.parse (issue #69). Mirrors axios's lenient default:
// try to parse any non-empty string body, hand it back untouched if it is not JSON.
axiosInstance.defaults.transformResponse = [
  (data: unknown) => {
    if (typeof data === "string" && data.length > 0) {
      try {
        return parseJsonWithBigIntIds(data);
      } catch {
        return data;
      }
    }
    return data;
  },
];

type MethodTypes = "get" | "delete" | "head" | "options";
type MethodTypesWithBody = "post" | "put" | "patch";

const dataProvider = (
  apiUrl: string,
  httpClient: AxiosInstance = axiosInstance,
): Omit<Required<DataProvider>, "createMany" | "updateMany" | "deleteMany"> => ({
  getList: async ({ resource, meta, pagination, sorters, filters }) => {
    const url = `${apiUrl}/${resource}`;

    const { headers: headersFromMeta, method } = meta ?? {};
    const queryParams: Record<string, string | number> = meta?.queryParams ?? {};
    const requestMethod = (method as MethodTypes) ?? "get";

    if (pagination && pagination.mode == "server") {
      const pageSize = pagination.pageSize ?? 10;
      const offset = ((pagination.currentPage ?? 1) - 1) * pageSize;
      queryParams["limit"] = pageSize;
      queryParams["offset"] = offset;
    }

    if (sorters && sorters.length > 0) {
      // Map all sorters, including custom field sorters
      queryParams["sort"] = sorters
        .map((sort) => {
          const field = sort.field;
          // Custom field sorters are already in the correct format (extra.field_key)
          return `${field}:${sort.order}`;
        })
        .join(",");
    }

    if (filters && filters.length > 0) {
      // Process regular filters
      filters.forEach((filter) => {
        if (!("field" in filter)) {
          throw Error("Filter must be a LogicalFilter.");
        }

        const field = filter.field;

        // Skip custom fields, they'll be handled separately
        if (typeof field === "string" && isCustomField(field)) {
          return;
        }

        if (filter.value.length > 0) {
          const filterValueArray = Array.isArray(filter.value) ? filter.value : [filter.value];
          queryParams[field] = serializeFilterValues(filterValueArray);
        }
      });

      // Process custom field filters
      const customFieldFilters = getCustomFieldFilters(filters);
      Object.entries(customFieldFilters).forEach(([key, values]) => {
        if (values.length > 0) {
          queryParams[`extra.${key}`] = serializeFilterValues(values);
        }
      });
    }

    const { data, headers } = await httpClient[requestMethod](`${url}`, {
      headers: headersFromMeta,
      params: queryParams,
    });

    return {
      data,
      total: parseInt(headers["x-total-count"]) ?? 100,
    };
  },

  getMany: async () => {
    throw new Error("getMany not implemented");
  },

  create: async ({ resource, variables, meta }) => {
    const url = `${apiUrl}/${resource}`;

    const { headers, method } = meta ?? {};
    const requestMethod = (method as MethodTypesWithBody) ?? "post";

    const { data } = await httpClient[requestMethod](url, variables, {
      headers,
    });

    return {
      data,
    };
  },

  update: async ({ resource, id, variables, meta }) => {
    const url = `${apiUrl}/${resource}/${id}`;

    const { headers, method } = meta ?? {};
    const requestMethod = (method as MethodTypesWithBody) ?? "patch";

    const { data } = await httpClient[requestMethod](url, variables, {
      headers,
    });

    return {
      data,
    };
  },

  getOne: async ({ resource, id, meta }) => {
    const url = `${apiUrl}/${resource}/${id}`;

    const { headers, method } = meta ?? {};
    const requestMethod = (method as MethodTypes) ?? "get";

    const { data } = await httpClient[requestMethod](url, { headers });

    return {
      data,
    };
  },

  deleteOne: async ({ resource, id, variables, meta }) => {
    const url = `${apiUrl}/${resource}/${id}`;

    const { headers, method } = meta ?? {};
    const requestMethod = (method as MethodTypesWithBody) ?? "delete";

    const { data } = await httpClient[requestMethod](url, {
      data: variables,
      headers,
    });

    return {
      data,
    };
  },

  getApiUrl: () => {
    return apiUrl;
  },

  custom: async ({ url, method, payload, query, headers }) => {
    let requestUrl = `${url}?`;

    if (query) {
      requestUrl = `${requestUrl}&${stringify(query)}`;
    }

    if (headers) {
      httpClient.defaults.headers.common = {
        ...httpClient.defaults.headers.common,
        ...headers,
      };
    }

    let axiosResponse;
    switch (method) {
      case "put":
      case "post":
      case "patch":
        axiosResponse = await httpClient[method](url, payload);
        break;
      case "delete":
        axiosResponse = await httpClient.delete(url, {
          data: payload,
        });
        break;
      default:
        axiosResponse = await httpClient.get(requestUrl);
        break;
    }

    const { data } = axiosResponse;

    return Promise.resolve({ data });
  },
});

export default dataProvider;
