import { DATE_TIME_FORMAT } from "../../utils/dateFormat";
import { Edit, useForm } from "@refinedev/antd";
import { HttpError, useTranslate } from "@refinedev/core";
import { Alert, ColorPicker, DatePicker, Divider, Form, Input, InputNumber, Radio, Select, Typography } from "antd";
import TextArea from "antd/es/input/TextArea";
import { message } from "antd/lib";
import dayjs from "dayjs";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { ExtraFieldFormItem, ParsedExtras, StringifiedExtras } from "../../components/extraFields";
import { useSpoolmanLocations } from "../../components/otherModels";
import { searchMatches } from "../../utils/filtering";
import { formatNumberOnUserInput, numberParser, numberParserAllowEmpty } from "../../utils/parsing";
import { EntityType, useGetFields } from "../../utils/queryFields";
import { useGetPrinters } from "../../utils/queryPrinters";
import { getCurrencySymbol, useCurrency } from "../../utils/settings";
import { createFilamentFromExternal } from "../filaments/functions";
import { useLocations } from "../locations/functions";
import { useGetFilamentSelectOptions } from "./functions";
import { ISpool, ISpoolParsedExtras, WeightToEnter } from "./model";
import { correctOverweight, displayForMode, usedWeightFromEntered } from "./weightCalc";

/*
The API returns the extra fields as JSON values, but we need to parse them into their real types
in order for Ant design's form to work properly. ParsedExtras does this for us.
We also need to stringify them again before sending them back to the API, which is done by overriding
the form's onFinish method. Form.Item's normalize should do this, but it doesn't seem to work.
*/

type ISpoolRequest = ISpoolParsedExtras & {
  filament_id: number | string;
  printer_id?: number | null;
};

export const SpoolEdit = () => {
  const t = useTranslate();
  const [messageApi, contextHolder] = message.useMessage();
  const [hasChanged, setHasChanged] = useState(false);
  const extraFields = useGetFields(EntityType.spool);
  const currency = useCurrency();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  const { form, formProps, saveButtonProps } = useForm<ISpool, HttpError, ISpoolRequest, ISpool>({
    liveMode: "manual",
    onLiveEvent() {
      // Warn the user if the spool has been updated since the form was opened
      messageApi.warning(t("spool.form.spool_updated"));
      setHasChanged(true);
    },

    // Custom redirect logic
    redirect: false,
    onMutationSuccess: () => {
      const returnUrl = searchParams.get("return");
      if (returnUrl) {
        navigate(returnUrl, { relative: "path" });
      } else {
        navigate("/spool");
      }
    },
  });

  const initialWeightValue = Form.useWatch("initial_weight", form);
  const spoolWeightValue = Form.useWatch("spool_weight", form);

  // Add the filament_id field to the form
  if (formProps.initialValues) {
    formProps.initialValues["filament_id"] = formProps.initialValues["filament"].id;
    // #75: map the nested printer object to the printer_id the form/select edits.
    formProps.initialValues["printer_id"] = formProps.initialValues["printer"]?.id;

    // Parse the extra fields from string values into real types
    formProps.initialValues = ParsedExtras(formProps.initialValues);
  }

  //
  // Set up the filament selection options
  //
  const {
    options: filamentOptions,
    internalSelectOptions,
    externalSelectOptions,
    allExternalFilaments,
  } = useGetFilamentSelectOptions();

  const selectedFilamentID = Form.useWatch("filament_id", form);
  const selectedFilament = useMemo(() => {
    // id is a number of it's an internal filament, and a string of it's an external filament.
    if (typeof selectedFilamentID === "number") {
      return (
        internalSelectOptions?.find((obj) => {
          return obj.value === selectedFilamentID;
        }) ?? null
      );
    } else if (typeof selectedFilamentID === "string") {
      return (
        externalSelectOptions?.find((obj) => {
          return obj.value === selectedFilamentID;
        }) ?? null
      );
    } else {
      return null;
    }
  }, [selectedFilamentID, internalSelectOptions, externalSelectOptions]);

  // Override the form's onFinish method to stringify the extra fields
  const originalOnFinish = formProps.onFinish;
  formProps.onFinish = (allValues: ISpoolRequest) => {
    if (allValues !== undefined && allValues !== null) {
      // Lot of stupidity here to make types work
      const values = StringifiedExtras<ISpoolRequest>(allValues);
      // #61: a spool heavier than its theoretical weight would submit a negative used_weight
      // (422 from the backend). Absorb the deficit into initial_weight, like measure() does.
      if ((values.used_weight ?? 0) < 0) {
        const corrected = correctOverweight(values.used_weight ?? 0, values.initial_weight ?? getFilamentWeight());
        values.used_weight = corrected.used;
        values.initial_weight = corrected.initial;
      }
      if (selectedFilament?.is_internal === false) {
        // Filament ID being a string indicates its an external filament.
        // If so, we should first create the internal filament version, then edit the spool
        const externalFilament = allExternalFilaments?.find((f) => f.id === values.filament_id);
        if (!externalFilament) {
          throw new Error("Unknown external filament");
        }
        createFilamentFromExternal(externalFilament).then((internalFilament) => {
          values.filament_id = internalFilament.id;
          originalOnFinish?.({
            extra: {},
            ...values,
          });
        });
      } else {
        originalOnFinish?.({
          extra: {},
          ...values,
        });
      }
    }
  };

  const [weightToEnter, setWeightToEnter] = useState(1);
  // #66: the value the user typed in the active weight mode is the source of truth; used_weight is
  // derived from it (below) so editing initial/spool weight recomputes it rather than drifting it.
  const [enteredValue, setEnteredValue] = useState(0);

  useEffect(() => {
    const newFilamentWeight = getFilamentWeight();
    const newSpoolWeight = getSpoolWeight();
    if (newFilamentWeight > 0) {
      form.setFieldValue("initial_weight", newFilamentWeight);
    }
    if (newSpoolWeight > 0) {
      form.setFieldValue("spool_weight", newSpoolWeight);
    }
  }, [selectedFilament]);

  const locations = useSpoolmanLocations(true);
  const printers = useGetPrinters();
  const settingsLocation = useLocations();
  const [newLocation, setNewLocation] = useState("");

  const allLocations = [...(settingsLocation || [])];
  locations?.data?.forEach((loc) => {
    if (!allLocations.includes(loc)) {
      allLocations.push(loc);
    }
  });
  if (newLocation.trim() && !allLocations.includes(newLocation)) {
    allLocations.push(newLocation.trim());
  }

  const getSpoolWeight = (): number => {
    return spoolWeightValue ?? selectedFilament?.spool_weight ?? 0;
  };

  const getFilamentWeight = (): number => {
    return initialWeightValue ?? selectedFilament?.weight ?? 0;
  };

  const getGrossWeight = (): number => {
    const net_weight = getFilamentWeight();
    const spool_weight = getSpoolWeight();
    return net_weight + spool_weight;
  };

  // #66: derive net used_weight from the entered value + current weights, preserving the entered value
  // when initial/spool weight changes.
  const usedWeight = usedWeightFromEntered(weightToEnter, enteredValue, getFilamentWeight(), getSpoolWeight());

  // Switch weight mode, converting the entered value so the shown number stays consistent.
  const switchWeightMode = (newMode: number) => {
    setEnteredValue(displayForMode(newMode, usedWeight, getFilamentWeight(), getSpoolWeight()));
    setWeightToEnter(newMode);
  };

  // Keep the hidden used_weight form field in sync with the derived value.
  useEffect(() => {
    form.setFieldValue("used_weight", usedWeight);
  }, [form, usedWeight]);

  const getMeasuredWeight = (): number => {
    const grossWeight = getGrossWeight();

    return grossWeight - usedWeight;
  };

  const getRemainingWeight = (): number => {
    const initial_weight = getFilamentWeight();

    return initial_weight - usedWeight;
  };

  const isMeasuredWeightEnabled = (): boolean => {
    if (!isRemainingWeightEnabled()) {
      return false;
    }

    const spool_weight = spoolWeightValue;

    return spool_weight || selectedFilament?.spool_weight ? true : false;
  };

  const isRemainingWeightEnabled = (): boolean => {
    const initial_weight = initialWeightValue;

    if (initial_weight) {
      return true;
    }

    return selectedFilament?.weight ? true : false;
  };

  useEffect(() => {
    // If the active mode is no longer valid, fall back a mode — converting the entered value so
    // used_weight is preserved (#66).
    if (weightToEnter >= WeightToEnter.measured_weight && !isMeasuredWeightEnabled()) {
      switchWeightMode(WeightToEnter.remaining_weight);
      return;
    }
    if (weightToEnter >= WeightToEnter.remaining_weight && !isRemainingWeightEnabled()) {
      switchWeightMode(WeightToEnter.used_weight);
    }
  }, [selectedFilament]);

  const initialUsedWeight = formProps.initialValues?.used_weight || 0;
  useEffect(() => {
    // Seed the entered value from the loaded spool. The mode defaults to "used", so the entered value
    // is the used_weight; if the mode later switches, switchWeightMode converts it (#66).
    if (initialUsedWeight) {
      setEnteredValue(initialUsedWeight);
    }
  }, [initialUsedWeight]);

  return (
    <Edit saveButtonProps={saveButtonProps}>
      {contextHolder}
      <Form {...formProps} layout="vertical">
        <Form.Item
          label={t("spool.fields.id")}
          name={["id"]}
          rules={[
            {
              required: true,
            },
          ]}
        >
          <Input readOnly disabled />
        </Form.Item>
        <Form.Item
          label={t("spool.fields.registered")}
          name={["registered"]}
          rules={[
            {
              required: true,
            },
          ]}
          getValueProps={(value) => ({
            value: value ? dayjs(value) : undefined,
          })}
        >
          <DatePicker disabled showTime format={DATE_TIME_FORMAT} />
        </Form.Item>
        <Form.Item
          label={t("spool.fields.first_used")}
          name={["first_used"]}
          rules={[
            {
              required: false,
            },
          ]}
          getValueProps={(value) => ({
            value: value ? dayjs(value) : undefined,
          })}
        >
          <DatePicker showTime format={DATE_TIME_FORMAT} />
        </Form.Item>
        <Form.Item
          label={t("spool.fields.last_used")}
          name={["last_used"]}
          rules={[
            {
              required: false,
            },
          ]}
          getValueProps={(value) => ({
            value: value ? dayjs(value) : undefined,
          })}
        >
          <DatePicker showTime format={DATE_TIME_FORMAT} />
        </Form.Item>
        <Form.Item
          label={t("spool.fields.filament")}
          name={["filament_id"]}
          rules={[
            {
              required: true,
            },
          ]}
        >
          <Select
            options={filamentOptions}
            showSearch
            filterOption={(input, option) => typeof option?.label === "string" && searchMatches(input, option?.label)}
          />
        </Form.Item>
        {selectedFilament?.is_internal === false && (
          <Alert message={t("spool.fields_help.external_filament")} type="info" />
        )}
        <Form.Item
          label={t("spool.fields.price")}
          help={t("spool.fields_help.price")}
          name={["price"]}
          rules={[
            {
              required: false,
              type: "number",
              min: 0,
            },
          ]}
        >
          <InputNumber
            addonAfter={getCurrencySymbol(undefined, currency)}
            precision={2}
            formatter={formatNumberOnUserInput}
            parser={numberParserAllowEmpty}
          />
        </Form.Item>
        <Form.Item
          label={t("spool.fields.initial_weight")}
          help={t("spool.fields_help.initial_weight")}
          name={["initial_weight"]}
          rules={[
            {
              required: false,
              type: "number",
              min: 0,
            },
          ]}
        >
          <InputNumber
            addonAfter="g"
            precision={1}
            formatter={formatNumberOnUserInput}
            parser={numberParserAllowEmpty}
          />
        </Form.Item>

        <Form.Item
          label={t("spool.fields.spool_weight")}
          help={t("spool.fields_help.spool_weight")}
          name={["spool_weight"]}
          rules={[
            {
              required: false,
              type: "number",
              min: 0,
            },
          ]}
        >
          <InputNumber
            addonAfter="g"
            precision={1}
            formatter={formatNumberOnUserInput}
            parser={numberParserAllowEmpty}
          />
        </Form.Item>

        <Form.Item hidden={true} name={["used_weight"]} initialValue={0}>
          <InputNumber value={usedWeight} />
        </Form.Item>

        <Form.Item label={t("spool.fields.weight_to_use")} help={t("spool.fields_help.weight_to_use")}>
          <Radio.Group
            onChange={(value) => {
              switchWeightMode(value.target.value);
            }}
            defaultValue={WeightToEnter.used_weight}
            value={weightToEnter}
          >
            <Radio.Button value={WeightToEnter.used_weight}>{t("spool.fields.used_weight")}</Radio.Button>
            <Radio.Button value={WeightToEnter.remaining_weight} disabled={!isRemainingWeightEnabled()}>
              {t("spool.fields.remaining_weight")}
            </Radio.Button>
            <Radio.Button value={WeightToEnter.measured_weight} disabled={!isMeasuredWeightEnabled()}>
              {t("spool.fields.measured_weight")}
            </Radio.Button>
          </Radio.Group>
        </Form.Item>
        <Form.Item label={t("spool.fields.used_weight")} help={t("spool.fields_help.used_weight")}>
          <InputNumber
            min={0}
            addonAfter="g"
            precision={1}
            formatter={formatNumberOnUserInput}
            parser={numberParser}
            disabled={weightToEnter != WeightToEnter.used_weight}
            value={usedWeight}
            onChange={(value) => {
              setEnteredValue(value ?? 0);
            }}
          />
        </Form.Item>
        <Form.Item label={t("spool.fields.remaining_weight")} help={t("spool.fields_help.remaining_weight")}>
          <InputNumber
            min={0}
            addonAfter="g"
            precision={1}
            formatter={formatNumberOnUserInput}
            parser={numberParser}
            disabled={weightToEnter != WeightToEnter.remaining_weight}
            value={getRemainingWeight()}
            onChange={(value) => {
              setEnteredValue(value ?? 0);
            }}
          />
        </Form.Item>
        <Form.Item label={t("spool.fields.measured_weight")} help={t("spool.fields_help.measured_weight")}>
          <InputNumber
            min={0}
            addonAfter="g"
            precision={1}
            formatter={formatNumberOnUserInput}
            parser={numberParser}
            disabled={weightToEnter != WeightToEnter.measured_weight}
            value={getMeasuredWeight()}
            onChange={(value) => {
              setEnteredValue(value ?? 0);
            }}
          />
        </Form.Item>
        <Form.Item
          label={t("spool.fields.location")}
          help={t("spool.fields_help.location")}
          name={["location"]}
          rules={[
            {
              required: false,
            },
          ]}
        >
          <Select
            dropdownRender={(menu) => (
              <>
                {menu}
                <Divider style={{ margin: "8px 0" }} />
                <Input
                  placeholder={t("spool.form.new_location_prompt")}
                  value={newLocation}
                  onChange={(event) => setNewLocation(event.target.value)}
                />
              </>
            )}
            loading={locations.isLoading}
            options={allLocations.map((item) => ({ label: item, value: item }))}
          />
        </Form.Item>
        {/* Printer assignment (#75): only shown once at least one printer exists. */}
        {printers.data && printers.data.length > 0 && (
          <Form.Item label={t("spool.fields.printer")} help={t("spool.fields_help.printer")} name={["printer_id"]}>
            <Select
              allowClear
              loading={printers.isLoading}
              options={printers.data.map((p) => ({ label: p.name, value: p.id }))}
            />
          </Form.Item>
        )}
        <Form.Item
          label={t("spool.fields.lot_nr")}
          help={t("spool.fields_help.lot_nr")}
          name={["lot_nr"]}
          rules={[
            {
              required: false,
            },
          ]}
        >
          <Input maxLength={64} />
        </Form.Item>
        <Form.Item
          label={t("spool.fields.diameter")}
          help={t("spool.fields_help.diameter")}
          name={["diameter"]}
          rules={[
            {
              required: false,
              type: "number",
              min: 0,
            },
          ]}
        >
          {/* #101: optional measured diameter; empty falls back to the filament's diameter. */}
          <InputNumber
            addonAfter="mm"
            precision={2}
            formatter={formatNumberOnUserInput}
            parser={numberParserAllowEmpty}
          />
        </Form.Item>
        <Form.Item
          label={t("spool.fields.color_hex")}
          help={t("spool.fields_help.color_hex")}
          name={"color_hex"}
          rules={[{ required: false }]}
          getValueFromEvent={(e) => e?.toHex()}
        >
          {/* #74: optional single-color override; clear to fall back to the filament color. */}
          <ColorPicker format="hex" allowClear />
        </Form.Item>
        <Form.Item
          label={t("spool.fields.comment")}
          name={["comment"]}
          rules={[
            {
              required: false,
            },
          ]}
        >
          <TextArea maxLength={1024} />
        </Form.Item>
        <Typography.Title level={5}>{t("settings.extra_fields.tab")}</Typography.Title>
        {extraFields.data?.map((field, index) => (
          <ExtraFieldFormItem key={index} field={field} />
        ))}
      </Form>
      {hasChanged && <Alert description={t("spool.form.spool_updated")} type="warning" showIcon />}
    </Edit>
  );
};

export default SpoolEdit;
