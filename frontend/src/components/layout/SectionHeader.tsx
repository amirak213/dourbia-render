interface SectionHeaderProps {
  title: string;
  subtitle?: string;
  as?: "header" | "div";
}

export default function SectionHeader({
  title,
  subtitle,
  as: Tag = "header",
}: SectionHeaderProps) {
  return (
    <Tag className="section-header page-header">
      <h1>{title}</h1>
      {subtitle && <p>{subtitle}</p>}
    </Tag>
  );
}
