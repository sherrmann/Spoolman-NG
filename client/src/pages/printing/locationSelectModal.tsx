import { RightOutlined } from "@ant-design/icons";
import { useList, useTranslate } from "@refinedev/core";
import { Button, Select, Space, message } from "antd";
import { useState } from "react";
import { ILocation } from "../locations/model";

/**
 * Pick which locations to print QR labels for (#84). Locations are few, so a plain multi-select is
 * enough — no heavy table like the spool picker needs.
 */
const LocationSelectModal = ({
  description,
  onContinue,
}: {
  description?: string;
  onContinue: (ids: number[]) => void;
}) => {
  const t = useTranslate();
  const [messageApi, contextHolder] = message.useMessage();
  const { result } = useList<ILocation>({ resource: "locations", pagination: { mode: "off" } });
  const [selected, setSelected] = useState<number[]>([]);

  return (
    <>
      {contextHolder}
      <Space direction="vertical" style={{ width: "100%" }}>
        {description && <div>{description}</div>}
        <Select
          mode="multiple"
          style={{ width: "100%" }}
          placeholder={t("locations.print.select_placeholder")}
          value={selected}
          onChange={setSelected}
          options={(result?.data ?? []).map((l) => ({ label: l.name, value: l.id }))}
          filterOption={(input, option) =>
            typeof option?.label === "string" && option.label.toLowerCase().includes(input.toLowerCase())
          }
        />
        <Button
          type="primary"
          icon={<RightOutlined />}
          iconPosition="end"
          onClick={() => {
            if (selected.length === 0) {
              messageApi.open({ type: "error", content: t("locations.print.none_selected") });
              return;
            }
            onContinue(selected);
          }}
        >
          {t("buttons.continue")}
        </Button>
      </Space>
    </>
  );
};

export default LocationSelectModal;
