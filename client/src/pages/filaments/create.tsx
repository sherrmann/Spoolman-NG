import { Create, useForm, useSelect } from "@refinedev/antd";
import { HttpError, IResourceComponentsProps, useInvalidate, useTranslate } from "@refinedev/core";
import {
  Button,
  ColorPicker,
  Divider,
  Form,
  Input,
  InputNumber,
  Radio,
  Select,
  Typography,
  message,
  Space,
} from "antd";
import TextArea from "antd/es/input/TextArea";
import dayjs from "dayjs";
import utc from "dayjs/plugin/utc";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router";
import { ExtraFieldFormItem, ParsedExtras, StringifiedExtras } from "../../components/extraFields";
import { FilamentImagePicker, uploadFilamentImage } from "../../components/filamentImageUpload";
import { FilamentImportModal } from "../../components/filamentImportModal";
import { FilamentCatalogFields } from "./catalogFields";
import { MultiColorPicker } from "../../components/multiColorPicker";
import { StickyFooterBar } from "../../components/stickyFooterBar";
import { suggestDensityForMaterial } from "../../utils/materialDensities";
import { PreparedImage } from "../../utils/imageTransform";
import { formatNumberOnUserInput, numberParser, numberParserAllowEmpty } from "../../utils/parsing";
import { ExternalFilament, fetchExternalProfile } from "../../utils/queryExternalDB";
import { EntityType, useGetFields } from "../../utils/queryFields";
import { getCurrencySymbol, useCurrency } from "../../utils/settings";
import { createVendor, getOrCreateVendorFromExternal } from "../vendors/functions";
import { IVendor } from "../vendors/model";
import { IFilament, IFilamentParsedExtras } from "./model";

dayjs.extend(utc);

interface CreateOrCloneProps {
  mode: "create" | "clone";
}

type IFilamentRequest = Omit<IFilamentParsedExtras, "id" | "registered"> & {
  vendor_id: number;
};

export const FilamentCreate = (props: IResourceComponentsProps & CreateOrCloneProps) => {
  const t = useTranslate();
  const extraFields = useGetFields(EntityType.filament);
  const currency = useCurrency();
  const [isImportExtOpen, setIsImportExtOpen] = useState(false);
  const invalidate = useInvalidate();
  const [colorType, setColorType] = useState<"single" | "multi">("single");
  const [profileId, setProfileId] = useState("");
  // #125: inline vendor creation from the vendor picker's dropdown.
  const [newVendorName, setNewVendorName] = useState("");
  const [addingVendor, setAddingVendor] = useState(false);
  // #97b: when a scanned retail barcode matched no filament, the scanner routes here with the code
  // as ?article_number= so the new filament remembers it and the next scan resolves.
  const [searchParams] = useSearchParams();
  // #88: the reference photo is staged locally (already downscaled) because there is no filament id
  // to PUT it to until the POST in handleSubmit has succeeded.
  const [stagedImage, setStagedImage] = useState<PreparedImage | null>(null);

  const { form, formProps, formLoading, onFinish, redirect } = useForm<
    IFilament,
    HttpError,
    IFilamentRequest,
    IFilamentParsedExtras
  >();

  if (!formProps.initialValues) {
    formProps.initialValues = {};
  }

  const prefillArticleNumber = searchParams.get("article_number");
  if (prefillArticleNumber && formProps.initialValues.article_number === undefined) {
    formProps.initialValues.article_number = prefillArticleNumber;
  }

  if (props.mode === "clone") {
    // Fix the vendor_id
    if (formProps.initialValues.vendor) {
      formProps.initialValues.vendor_id = formProps.initialValues.vendor.id;
    }

    // Parse the extra fields from string values into real types
    formProps.initialValues = ParsedExtras(formProps.initialValues);
  }

  const handleSubmit = async (redirectTo: "list" | "create") => {
    const values = StringifiedExtras(await form.validateFields());
    const response = await onFinish(values);
    // A staged photo (#88) can only be attached after the POST has produced an id, so PUT it
    // before redirecting. A failed photo upload keeps the created filament and just reports.
    const createdId = response && "data" in response ? response.data?.id : undefined;
    if (createdId !== undefined && stagedImage) {
      try {
        await uploadFilamentImage(createdId, stagedImage);
        setStagedImage(null);
      } catch (err) {
        console.error(err);
        message.error(t("filament.image.upload_error"));
      }
    }
    redirect(redirectTo);
  };

  const { selectProps: vendorSelect } = useSelect<IVendor>({
    resource: "vendor",
    optionLabel: "name",
    pagination: { mode: "off" },
  });

  const importFilament = async (filament: ExternalFilament) => {
    const vendor = await getOrCreateVendorFromExternal(filament.manufacturer);
    await invalidate({
      resource: "vendor",
      invalidates: ["list", "detail"],
    });

    setColorType(filament.color_hexes ? "multi" : "single");

    form.setFieldsValue({
      name: filament.name,
      vendor_id: vendor.id,
      material: filament.material,
      density: filament.density,
      diameter: filament.diameter,
      weight: filament.weight,
      spool_weight: filament.spool_weight || undefined,
      color_hex: filament.color_hex,
      multi_color_hexes: filament.color_hexes?.join(",") || undefined,
      multi_color_direction: filament.multi_color_direction,
      settings_extruder_temp: filament.extruder_temp || undefined,
      settings_bed_temp: filament.bed_temp || undefined,
      settings_extruder_temp_min: filament.extruder_temp_min || undefined,
      settings_extruder_temp_max: filament.extruder_temp_max || undefined,
      settings_bed_temp_min: filament.bed_temp_min || undefined,
      settings_bed_temp_max: filament.bed_temp_max || undefined,
      spool_type: filament.spool_type,
      finish: filament.finish,
      pattern: filament.pattern,
      // Only carry a positive translucent/glow signal — false is indistinguishable from "unknown"
      // in the catalog, so leave it unset rather than asserting the filament is not translucent.
      translucent: filament.translucent || undefined,
      glow: filament.glow || undefined,
    });
  };

  // #125: create a vendor inline from the picker without leaving the filament form. After the POST
  // we invalidate the vendor list so the useSelect refetches (the same get-or-create + invalidate
  // pattern importFilament already uses), then select the new vendor.
  const addVendor = async () => {
    const name = newVendorName.trim();
    if (!name) return;
    setAddingVendor(true);
    try {
      const vendor = await createVendor(name);
      await invalidate({ resource: "vendor", invalidates: ["list", "detail"] });
      form.setFieldValue("vendor_id", vendor.id);
      setNewVendorName("");
      message.success(t("filament.form.vendor_created"));
    } catch (err) {
      console.error(err);
      message.error(t("filament.form.vendor_create_error"));
    } finally {
      setAddingVendor(false);
    }
  };

  const fetchProfile = async () => {
    if (!profileId) return;
    try {
      const filament = await fetchExternalProfile(profileId);
      await importFilament(filament);
      message.success(t("filament.form.import_3dfp_success"));
    } catch (err) {
      console.error(err);
      message.error(t("filament.form.import_3dfp_error"));
    }
  };

  // Use useEffect to update the form's initialValues when the extra fields are loaded
  // This is necessary because the form is rendered before the extra fields are loaded
  useEffect(() => {
    extraFields.data?.forEach((field) => {
      if (formProps.initialValues && field.default_value) {
        const parsedValue = JSON.parse(field.default_value as string);
        form.setFieldsValue({ extra: { [field.key]: parsedValue } });
      }
    });
  }, [form, extraFields.data, formProps.initialValues]);

  return (
    <Create
      title={props.mode === "create" ? t("filament.titles.create") : t("filament.titles.clone")}
      isLoading={formLoading}
      headerButtons={() => (
        <>
          <Button type="primary" onClick={() => setIsImportExtOpen(true)}>
            {t("filament.form.import_external")}
          </Button>
        </>
      )}
      footerButtons={() => (
        <StickyFooterBar>
          <Button type="primary" onClick={() => handleSubmit("list")}>
            {t("buttons.save")}
          </Button>
          <Button type="primary" onClick={() => handleSubmit("create")}>
            {t("buttons.saveAndAdd")}
          </Button>
        </StickyFooterBar>
      )}
    >
      <FilamentImportModal
        isOpen={isImportExtOpen}
        onImport={(value) => {
          setIsImportExtOpen(false);
          importFilament(value);
        }}
        onClose={() => setIsImportExtOpen(false)}
      />
      {/* onFinish → Save so pressing Enter in a field submits the form (#127). The 3dfp import input
          above calls preventDefault on Enter, so it fetches rather than submitting. */}
      <Form {...formProps} layout="vertical" onFinish={() => handleSubmit("list")}>
        <Form.Item label={t("filament.form.import_3dfp")} help={t("filament.form.import_3dfp_help")}>
          <Space.Compact style={{ width: "100%" }}>
            <Input
              value={profileId}
              onChange={(e) => setProfileId(e.target.value)}
              onPressEnter={(e) => {
                e.preventDefault();
                fetchProfile();
              }}
              placeholder={t("filament.form.import_3dfp_placeholder")}
            />
            <Button type="primary" onClick={fetchProfile}>
              {t("filament.buttons.fetch")}
            </Button>
          </Space.Compact>
        </Form.Item>
        <Form.Item
          label={t("filament.fields.name")}
          help={t("filament.fields_help.name")}
          name={["name"]}
          rules={[
            {
              required: false,
            },
          ]}
        >
          {/* Auto-focus the first real field (#127). */}
          <Input maxLength={64} autoFocus />
        </Form.Item>
        <Form.Item
          label={t("filament.fields.vendor")}
          name={["vendor_id"]}
          rules={[
            {
              required: false,
            },
          ]}
        >
          <Select
            {...vendorSelect}
            allowClear
            filterSort={(a, b) => {
              return a?.label && b?.label
                ? (a.label as string).localeCompare(b.label as string, undefined, { sensitivity: "base" })
                : 0;
            }}
            filterOption={(input, option) =>
              typeof option?.label === "string" && option?.label.toLowerCase().includes(input.toLowerCase())
            }
            // #125: let the user add a new manufacturer inline instead of leaving the form. Mirrors
            // the free-text location picker on the spool form, but a vendor must be POSTed to get an
            // id before the filament can reference it, so this has an explicit Create action.
            dropdownRender={(menu) => (
              <>
                {menu}
                <Divider style={{ margin: "8px 0" }} />
                <Space.Compact style={{ width: "100%", padding: "0 8px 4px" }}>
                  <Input
                    placeholder={t("filament.form.new_vendor_prompt")}
                    value={newVendorName}
                    onChange={(e) => setNewVendorName(e.target.value)}
                    onPressEnter={(e) => {
                      // Create the vendor, and stop Enter from bubbling to the form's implicit-submit
                      // button (#127) or the Select's own option handling.
                      e.preventDefault();
                      e.stopPropagation();
                      addVendor();
                    }}
                  />
                  <Button type="primary" loading={addingVendor} onClick={addVendor}>
                    {t("buttons.create")}
                  </Button>
                </Space.Compact>
              </>
            )}
          />
        </Form.Item>
        <Form.Item label={t("filament.fields.color_hex")}>
          <Radio.Group
            onChange={(value) => {
              setColorType(value.target.value);
            }}
            defaultValue={colorType}
            value={colorType}
          >
            <Radio.Button value={"single"}>{t("filament.fields.single_color")}</Radio.Button>
            <Radio.Button value={"multi"}>{t("filament.fields.multi_color")}</Radio.Button>
          </Radio.Group>
        </Form.Item>
        {colorType == "single" && (
          <Form.Item
            name={"color_hex"}
            rules={[
              {
                required: false,
              },
            ]}
            getValueFromEvent={(e) => {
              return e?.toHex();
            }}
          >
            <ColorPicker format="hex" />
          </Form.Item>
        )}
        {colorType == "multi" && (
          <Form.Item
            name={"multi_color_direction"}
            help={t("filament.fields_help.multi_color_direction")}
            rules={[
              {
                required: true,
              },
            ]}
            initialValue={"coaxial"}
          >
            <Radio.Group>
              <Radio.Button value={"coaxial"}>{t("filament.fields.coaxial")}</Radio.Button>
              <Radio.Button value={"longitudinal"}>{t("filament.fields.longitudinal")}</Radio.Button>
            </Radio.Group>
          </Form.Item>
        )}
        {colorType == "multi" && (
          <Form.Item
            name={"multi_color_hexes"}
            rules={[
              {
                required: false,
              },
            ]}
          >
            <MultiColorPicker min={2} max={14} />
          </Form.Item>
        )}
        {/* The photo (#88) is not a form value — it is staged here and PUT after the POST in
            handleSubmit — so this Form.Item is label-and-layout only (no name). */}
        <Form.Item label={t("filament.fields.image")} help={t("filament.fields_help.image")}>
          <FilamentImagePicker value={stagedImage} onChange={setStagedImage} />
        </Form.Item>
        <Form.Item
          label={t("filament.fields.material")}
          help={t("filament.fields_help.material")}
          name={["material"]}
          rules={[
            {
              required: false,
            },
          ]}
        >
          <Input
            maxLength={64}
            onChange={(e) => {
              // Suggest a density for a known material, but only when the field is still
              // blank so we never overwrite a value the user typed. Issue #54.
              const suggestion = suggestDensityForMaterial(e.target.value);
              if (suggestion !== undefined && form.getFieldValue("density") == null) {
                form.setFieldValue("density", suggestion);
              }
            }}
          />
        </Form.Item>
        <Form.Item
          label={t("filament.fields.price")}
          help={t("filament.fields_help.price")}
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
          label={t("filament.fields.density")}
          name={["density"]}
          rules={[
            {
              required: true,
              type: "number",
              max: 100,
            },
            {
              // Backend requires density > 0; reject 0 (numberParser turns an empty field into 0) with a
              // clear message instead of an opaque 422 (#67).
              validator: (_, value) =>
                value === undefined || value === null || value > 0
                  ? Promise.resolve()
                  : Promise.reject(new Error(t("filament.form.must_be_positive"))),
            },
          ]}
        >
          <InputNumber addonAfter="g/cm³" precision={2} formatter={formatNumberOnUserInput} parser={numberParser} />
        </Form.Item>
        <Form.Item
          label={t("filament.fields.diameter")}
          name={["diameter"]}
          rules={[
            {
              required: true,
              type: "number",
              max: 10,
            },
            {
              // Backend requires diameter > 0; reject 0 with a clear message instead of a 422 (#67).
              validator: (_, value) =>
                value === undefined || value === null || value > 0
                  ? Promise.resolve()
                  : Promise.reject(new Error(t("filament.form.must_be_positive"))),
            },
          ]}
        >
          <InputNumber addonAfter="mm" precision={2} formatter={formatNumberOnUserInput} parser={numberParser} />
        </Form.Item>
        <Form.Item
          label={t("filament.fields.weight")}
          help={t("filament.fields_help.weight")}
          name={["weight"]}
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
          label={t("filament.fields.spool_weight")}
          help={t("filament.fields_help.spool_weight")}
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
        <Form.Item
          label={t("filament.fields.low_stock_threshold")}
          help={t("filament.fields_help.low_stock_threshold")}
          name={["low_stock_threshold"]}
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
          label={t("filament.fields.reserve_count")}
          help={t("filament.fields_help.reserve_count")}
          name={["reserve_count"]}
          rules={[
            {
              required: false,
              type: "number",
              min: 0,
            },
          ]}
        >
          <InputNumber precision={0} />
        </Form.Item>
        <Form.Item
          label={t("filament.fields.settings_extruder_temp")}
          name={["settings_extruder_temp"]}
          rules={[
            {
              required: false,
              type: "number",
              min: 0,
            },
          ]}
        >
          <InputNumber addonAfter="°C" precision={0} />
        </Form.Item>
        <Form.Item
          label={t("filament.fields.settings_bed_temp")}
          name={["settings_bed_temp"]}
          rules={[
            {
              required: false,
              type: "number",
              min: 0,
            },
          ]}
        >
          <InputNumber addonAfter="°C" precision={0} />
        </Form.Item>
        <Form.Item
          label={t("filament.fields.settings_extruder_temp_range")}
          help={t("filament.fields_help.settings_extruder_temp_range")}
        >
          <Space.Compact>
            <Form.Item name={["settings_extruder_temp_min"]} noStyle rules={[{ type: "number", min: 0 }]}>
              <InputNumber precision={0} placeholder={t("filament.fields.temp_range_min")} />
            </Form.Item>
            <Form.Item name={["settings_extruder_temp_max"]} noStyle rules={[{ type: "number", min: 0 }]}>
              <InputNumber addonAfter="°C" precision={0} placeholder={t("filament.fields.temp_range_max")} />
            </Form.Item>
          </Space.Compact>
        </Form.Item>
        <Form.Item
          label={t("filament.fields.settings_bed_temp_range")}
          help={t("filament.fields_help.settings_bed_temp_range")}
        >
          <Space.Compact>
            <Form.Item name={["settings_bed_temp_min"]} noStyle rules={[{ type: "number", min: 0 }]}>
              <InputNumber precision={0} placeholder={t("filament.fields.temp_range_min")} />
            </Form.Item>
            <Form.Item name={["settings_bed_temp_max"]} noStyle rules={[{ type: "number", min: 0 }]}>
              <InputNumber addonAfter="°C" precision={0} placeholder={t("filament.fields.temp_range_max")} />
            </Form.Item>
          </Space.Compact>
        </Form.Item>
        <FilamentCatalogFields />
        <Form.Item
          label={t("filament.fields.article_number")}
          help={t("filament.fields_help.article_number")}
          name={["article_number"]}
          rules={[
            {
              required: false,
            },
          ]}
        >
          <Input maxLength={64} />
        </Form.Item>
        {/* External ID: editable in Edit and shown in Show, so offer it on Create too (#70). */}
        <Form.Item
          label={t("filament.fields.external_id")}
          name={["external_id"]}
          rules={[
            {
              required: false,
            },
          ]}
        >
          <Input maxLength={64} />
        </Form.Item>
        <Form.Item
          label={t("filament.fields.comment")}
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
        {/* Off-screen submit button so Enter submits the form (#127); the visible Save buttons are in
            footerButtons, outside the <Form>. */}
        <button
          type="submit"
          aria-hidden
          tabIndex={-1}
          style={{ position: "absolute", left: -9999, width: 1, height: 1 }}
        />
      </Form>
    </Create>
  );
};

export default FilamentCreate;
