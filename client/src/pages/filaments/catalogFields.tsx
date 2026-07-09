import { useTranslate } from "@refinedev/core";
import { Form, Select } from "antd";

// The five SpoolmanDB catalog descriptors (#91 / #567). Rendered identically on the filament
// create and edit forms, so they live in one shared component to stay in sync. Every field is
// optional and clearable — an empty value means "unknown" and is stored as null.
export function FilamentCatalogFields() {
  const t = useTranslate();
  const yesNo = [
    { value: true, label: t("yes") },
    { value: false, label: t("no") },
  ];
  return (
    <>
      <Form.Item label={t("filament.fields.spool_type")} name={["spool_type"]}>
        <Select
          allowClear
          options={[
            { value: "plastic", label: t("filament.spool_type_options.plastic") },
            { value: "cardboard", label: t("filament.spool_type_options.cardboard") },
            { value: "metal", label: t("filament.spool_type_options.metal") },
          ]}
        />
      </Form.Item>
      <Form.Item label={t("filament.fields.finish")} name={["finish"]}>
        <Select
          allowClear
          options={[
            { value: "matte", label: t("filament.finish_options.matte") },
            { value: "glossy", label: t("filament.finish_options.glossy") },
          ]}
        />
      </Form.Item>
      <Form.Item label={t("filament.fields.pattern")} name={["pattern"]}>
        <Select
          allowClear
          options={[
            { value: "marble", label: t("filament.pattern_options.marble") },
            { value: "sparkle", label: t("filament.pattern_options.sparkle") },
          ]}
        />
      </Form.Item>
      <Form.Item label={t("filament.fields.translucent")} name={["translucent"]}>
        <Select allowClear options={yesNo} />
      </Form.Item>
      <Form.Item label={t("filament.fields.glow")} name={["glow"]}>
        <Select allowClear options={yesNo} />
      </Form.Item>
    </>
  );
}
