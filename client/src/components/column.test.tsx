import { describe, expect, it } from "vitest";
import { CustomFieldColumn } from "./column";
import { EntityType, Field, FieldType } from "../utils/queryFields";
import { TableState } from "../utils/saveload";

// #83: CustomFieldColumn gained an `entityPrefix` so a spool list can show a filament's custom fields.
// These tests pin the contract that matters for compatibility: the entity's OWN fields stay
// interactive (sortable/filterable) exactly as before, while a related entity's fields are namespaced
// and rendered read-only (no sort/filter), because the list endpoint can't join into the related
// field table yet.

const tableState: TableState = {
  sorters: [],
  filters: [],
  pagination: { currentPage: 1, pageSize: 20 },
  showColumns: undefined,
};

const baseProps = {
  t: (key: string) => key,
  navigate: () => {},
  dataSource: [] as { id: number }[],
  tableState,
};

function field(overrides: Partial<Field> = {}): Field {
  return {
    key: "glitter",
    name: "Glitter",
    order: 0,
    field_type: FieldType.text,
    entity_type: EntityType.filament,
    ...overrides,
  };
}

describe("CustomFieldColumn", () => {
  it("keeps the entity's own field interactive and namespaced under extra", () => {
    const col = CustomFieldColumn<{ id: number }>({ ...baseProps, field: field() });
    expect(col?.dataIndex).toEqual(["extra", "glitter"]);
    expect(col?.sorter).toBe(true);
  });

  it("renders a related entity's field read-only and namespaced under the prefix", () => {
    const col = CustomFieldColumn<{ id: number }>({
      ...baseProps,
      field: field(),
      entityPrefix: ["filament"],
      title: "Glitter (Filament)",
    });
    // Namespaced so a spool field and a filament field can share a key without colliding.
    expect(col?.dataIndex).toEqual(["filament", "extra", "glitter"]);
    expect(col?.title).toBe("Glitter (Filament)");
    // Read-only: no sort affordance and no filter dropdown, so the client never asks the spool
    // endpoint to sort/filter by a filament field (which it cannot do yet).
    expect(col?.sorter).toBeFalsy();
    expect(col?.filterDropdown).toBeUndefined();
  });

  it("omits the filter list for a related boolean field", () => {
    const col = CustomFieldColumn<{ id: number }>({
      ...baseProps,
      field: field({ key: "dry", name: "Dry", field_type: FieldType.boolean }),
      entityPrefix: ["filament"],
    });
    expect(col?.dataIndex).toEqual(["filament", "extra", "dry"]);
    expect(col?.filters).toBeUndefined();
    expect(col?.sorter).toBeFalsy();
  });
});
