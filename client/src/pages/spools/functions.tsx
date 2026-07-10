import { useInvalidate, useSelect, useTranslate } from "@refinedev/core";
import { useQueries, useQueryClient } from "@tanstack/react-query";
import { Form, InputNumber, Modal, Radio } from "antd";
import { useForm } from "antd/es/form/Form";
import type { InputNumberRef } from "rc-input-number";
import { useCallback, useMemo, useRef, useState } from "react";
import { formatLength, formatNumberOnUserInput, formatWeight, numberParser } from "../../utils/parsing";
import { SpoolType, useGetExternalDBFilaments } from "../../utils/queryExternalDB";
import { useSavedState } from "../../utils/saveload";
import { getAPIURL } from "../../utils/url";
import { IFilament } from "../filaments/model";
import { ISpool } from "./model";

export async function setSpoolArchived(spool: ISpool, archived: boolean) {
  const init: RequestInit = {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      archived: archived,
    }),
  };
  const request = new Request(getAPIURL() + "/spool/" + spool.id);
  await fetch(request, init);
}

/**
 * Use some spool filament from this spool. Either specify length or weight.
 * @param spool The spool
 * @param length The length to add/subtract from the spool, in mm
 * @param weight The weight to add/subtract from the spool, in g
 */
export async function useSpoolFilament(spool: ISpool, length?: number, weight?: number) {
  const init: RequestInit = {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      use_length: length,
      use_weight: weight,
    }),
  };
  const request = new Request(`${getAPIURL()}/spool/${spool.id}/use`);
  await fetch(request, init);
}

/**
 * Adjust usage based on the spool's current gross weight
 * @param spool The spool
 * @param weight The weight of the spool, in g
 */
export async function useSpoolFilamentMeasure(spool: ISpool, weight: number) {
  const init: RequestInit = {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      weight: weight,
    }),
  };
  const request = new Request(`${getAPIURL()}/spool/${spool.id}/measure`);
  await fetch(request, init);
}

/**
 * Returns an array of queries using the useQueries hook from @tanstack/react-query.
 * Each query fetches a spool by its ID from the server.
 *
 * @param {number[]} ids - An array of spool IDs to fetch.
 * @return An array of query results, each containing the fetched spool data.
 */
export function useGetSpoolsByIds(ids: number[]) {
  return useQueries({
    queries: ids.map((id) => {
      return {
        queryKey: ["spool", id],
        queryFn: async () => {
          const res = await fetch(getAPIURL() + "/spool/" + id);
          return (await res.json()) as ISpool;
        },
      };
    }),
  });
}

/** The colour shape SpoolIcon accepts: a single hex string, or a multi-colour spec. */
export type FilamentColor = string | { colors: string[]; vertical: boolean };

/**
 * Build the SpoolIcon colour for a filament from its raw colour fields (#126). Multi-colour wins
 * when present; otherwise the single hex; `undefined` when the filament has no colour (SpoolIcon
 * then draws its neutral "?" placeholder). `direction === "longitudinal"` maps to a vertical split,
 * matching how the spool show page renders the swatch.
 */
export function filamentColorObj(
  colorHex: string | undefined,
  multiColorHexes: string[] | undefined,
  direction: string | undefined,
): FilamentColor | undefined {
  if (multiColorHexes && multiColorHexes.length > 0) {
    return { colors: multiColorHexes, vertical: direction === "longitudinal" };
  }
  return colorHex || undefined;
}

/**
 * Formats a filament label with the given parameters.
 */
export function formatFilamentLabel(
  name: string,
  diameter: number,
  vendorName?: string,
  material?: string,
  weight?: number,
  spoolType?: SpoolType,
): string {
  const portions = [];
  if (vendorName) {
    portions.push(vendorName);
  }
  portions.push(name);
  const extras = [];
  if (material) {
    extras.push(material);
  }
  extras.push(formatLength(diameter));
  if (weight) {
    extras.push(formatWeight(weight));
  }
  if (spoolType) {
    extras.push(spoolType.charAt(0).toUpperCase() + spoolType.slice(1) + " spool");
  }
  return `${portions.join(" - ")} (${extras.join(", ")})`;
}

interface SelectOption {
  label: string;
  value: string | number;
  weight?: number;
  spool_weight?: number;
  is_internal: boolean;
  // Colour swatch data for the dropdown (#126); undefined when the filament has no colour.
  colorObj?: FilamentColor;
}

export function useGetFilamentSelectOptions() {
  // Setup hooks
  const t = useTranslate();
  const { query: internalFilaments } = useSelect<IFilament>({
    resource: "filament",
    pagination: { mode: "off" },
  });
  const externalFilaments = useGetExternalDBFilaments();

  // Format and sort internal filament options
  const filamentSelectInternal: SelectOption[] = useMemo(() => {
    const data =
      internalFilaments.data?.data.map((item) => {
        return {
          label: formatFilamentLabel(
            item.name ?? `ID ${item.id}`,
            item.diameter,
            item.vendor?.name,
            item.material,
            item.weight,
          ),
          value: item.id,
          weight: item.weight,
          spool_weight: item.spool_weight,
          is_internal: true,
          colorObj: filamentColorObj(
            item.color_hex,
            item.multi_color_hexes ? item.multi_color_hexes.split(",") : undefined,
            item.multi_color_direction,
          ),
        };
      }) ?? [];
    data.sort((a, b) => a.label.localeCompare(b.label, undefined, { sensitivity: "base" }));
    return data;
  }, [internalFilaments.data?.data]);

  // Format and sort external filament options
  const filamentSelectExternal: SelectOption[] = useMemo(() => {
    const data =
      externalFilaments.data?.map((item) => {
        return {
          label: formatFilamentLabel(
            item.name,
            item.diameter,
            item.manufacturer,
            item.material,
            item.weight,
            item.spool_type,
          ),
          value: item.id,
          weight: item.weight,
          spool_weight: item.spool_weight || undefined,
          is_internal: false,
          colorObj: filamentColorObj(item.color_hex, item.color_hexes, item.multi_color_direction),
        };
      }) ?? [];
    data.sort((a, b) => a.label.localeCompare(b.label, undefined, { sensitivity: "base" }));
    return data;
  }, [externalFilaments.data]);

  return {
    options: [
      {
        label: <span>{t("spool.fields.filament_internal")}</span>,
        options: filamentSelectInternal,
      },
      {
        label: <span>{t("spool.fields.filament_external")}</span>,
        options: filamentSelectExternal,
      },
    ],
    internalSelectOptions: filamentSelectInternal,
    externalSelectOptions: filamentSelectExternal,
    allExternalFilaments: externalFilaments.data,
  };
}

type MeasurementType = "length" | "weight" | "measured_weight";

export function useSpoolAdjustModal() {
  const t = useTranslate();
  const [form] = useForm();
  const queryClient = useQueryClient();
  const invalidate = useInvalidate();

  const [curSpool, setCurSpool] = useState<ISpool | null>(null);
  // Persist the consumption mode across sessions so a reload doesn't silently reset it to
  // "length" and risk a wrong-unit entry. Issue #117.
  const [measurementType, setMeasurementType] = useSavedState<MeasurementType>("spoolAdjust-measurementType", "length");
  const inputNumberRef = useRef<InputNumberRef | null>(null);

  const openSpoolAdjustModal = useCallback((spool: ISpool) => {
    setCurSpool(spool);
    setTimeout(() => {
      inputNumberRef.current?.focus();
    }, 0);
  }, []);

  const spoolAdjustModal = useMemo(() => {
    if (curSpool === null) {
      return null;
    }

    const onSubmit = async () => {
      if (curSpool === null) {
        return;
      }

      const value = form.getFieldValue("filament_value");
      if (value === undefined || value === null) {
        return;
      }

      if (measurementType === "length") {
        await useSpoolFilament(curSpool, value, undefined);
      } else if (measurementType === "weight") {
        await useSpoolFilament(curSpool, undefined, value);
      } else {
        await useSpoolFilamentMeasure(curSpool, value);
      }

      // The adjustment changed the spool's counters AND appended to its usage log —
      // refresh both immediately so the show page's Usage history doesn't lag until
      // the next full reload.
      await queryClient.invalidateQueries({ queryKey: ["spool", curSpool.id, "events"] });
      invalidate({ resource: "spool", id: curSpool.id, invalidates: ["detail", "list"] });

      setCurSpool(null);
    };

    return (
      <Modal title={t("spool.titles.adjust")} open onCancel={() => setCurSpool(null)} onOk={form.submit}>
        <p>{t("spool.form.adjust_filament_help")}</p>
        <Form form={form} initialValues={{ measurement_type: measurementType }} onFinish={onSubmit}>
          <Form.Item label={t("spool.form.measurement_type_label")} name="measurement_type">
            <Radio.Group
              value={measurementType}
              onChange={({ target: { value } }) => setMeasurementType(value as MeasurementType)}
            >
              <Radio.Button value="length">{t("spool.form.measurement_type.length")}</Radio.Button>
              <Radio.Button value="weight">{t("spool.form.measurement_type.weight")}</Radio.Button>
              <Radio.Button value="measured_weight">{t("spool.fields.measured_weight")}</Radio.Button>
            </Radio.Group>
          </Form.Item>
          <Form.Item label={t("spool.form.adjust_filament_value")} name="filament_value">
            <InputNumber
              ref={inputNumberRef}
              precision={1}
              addonAfter={measurementType === "length" ? "mm" : "g"}
              formatter={formatNumberOnUserInput}
              parser={numberParser}
            />
          </Form.Item>
        </Form>
      </Modal>
    );
  }, [curSpool, measurementType, t, queryClient, invalidate, form]);

  return {
    openSpoolAdjustModal,
    spoolAdjustModal,
  };
}
