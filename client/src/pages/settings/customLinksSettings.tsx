import { PlusOutlined } from "@ant-design/icons";
import { useTranslate } from "@refinedev/core";
import { Button, Flex, Form, Input, Modal, Popconfirm, Table, message } from "antd";
import { useMemo, useState } from "react";
import { Trans } from "react-i18next";
import { CustomLink, parseCustomLinks } from "../../utils/customLinks";
import { useGetSetting, useSetSetting } from "../../utils/querySettings";

// A generic editor for a settings-backed list of {name, url} links, shared by the custom sidebar
// links (#92) and the per-spool action links (#140). The whole array is saved on every change.
export function CustomLinksSettings(props: {
  settingKey: string;
  descriptionKey: string;
  urlLabelKey: string;
  urlHelpKey?: string;
  urlPlaceholder: string;
}) {
  const t = useTranslate();
  const urlLabel = t(props.urlLabelKey);
  const urlHelp = props.urlHelpKey ? t(props.urlHelpKey) : undefined;
  const setting = useGetSetting(props.settingKey);
  const setSetting = useSetSetting<CustomLink[]>(props.settingKey);
  const links = useMemo(() => parseCustomLinks(setting.data?.value), [setting.data?.value]);

  const [form] = Form.useForm();
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [isOpen, setIsOpen] = useState(false);
  const [messageApi, contextHolder] = message.useMessage();

  const save = async (next: CustomLink[]) => {
    try {
      await setSetting.mutateAsync(next);
    } catch (e) {
      if (e instanceof Error) messageApi.error(e.message);
    }
  };

  const openCreate = () => {
    setEditingIndex(null);
    form.resetFields();
    setIsOpen(true);
  };

  const openEdit = (index: number) => {
    setEditingIndex(index);
    form.setFieldsValue(links[index]);
    setIsOpen(true);
  };

  const submit = async () => {
    let values: CustomLink;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    const next = [...links];
    if (editingIndex === null) {
      next.push(values);
    } else {
      next[editingIndex] = values;
    }
    await save(next);
    setIsOpen(false);
  };

  const remove = async (index: number) => {
    await save(links.filter((_, i) => i !== index));
  };

  return (
    <>
      <Trans i18nKey={props.descriptionKey} components={{ p: <p /> }} />
      <Table
        rowKey={(_, index) => String(index)}
        dataSource={links}
        loading={setting.isLoading}
        pagination={false}
        columns={[
          { title: t("settings.custom_links.name"), dataIndex: "name" },
          { title: urlLabel, dataIndex: "url" },
          {
            title: "",
            width: "20%",
            render: (_, _record, index: number) => (
              <Flex gap="small">
                <Button size="small" onClick={() => openEdit(index)}>
                  {t("buttons.edit")}
                </Button>
                <Popconfirm
                  title={t("settings.custom_links.delete_confirm")}
                  onConfirm={() => remove(index)}
                  okText={t("buttons.delete")}
                  cancelText={t("buttons.cancel")}
                >
                  <Button size="small" danger>
                    {t("buttons.delete")}
                  </Button>
                </Popconfirm>
              </Flex>
            ),
          },
        ]}
      />
      <Flex justify="center">
        <Button
          type="primary"
          shape="circle"
          icon={<PlusOutlined />}
          size="large"
          style={{ margin: "1em" }}
          onClick={openCreate}
        />
      </Flex>
      <Modal
        open={isOpen}
        title={editingIndex === null ? t("settings.custom_links.add_title") : t("settings.custom_links.edit_title")}
        onOk={submit}
        onCancel={() => setIsOpen(false)}
        confirmLoading={setSetting.isPending}
      >
        <Form form={form} layout="vertical">
          <Form.Item label={t("settings.custom_links.name")} name="name" rules={[{ required: true, max: 128 }]}>
            <Input />
          </Form.Item>
          <Form.Item label={urlLabel} help={urlHelp} name="url" rules={[{ required: true, max: 512 }]}>
            <Input placeholder={props.urlPlaceholder} />
          </Form.Item>
        </Form>
      </Modal>
      {contextHolder}
    </>
  );
}
