const Type = ({ category }) => {
  // Get badge variant class based on category
  const getBadgeVariant = () => {
    if (!category) return "";
    const lowerCategory = category.toLowerCase();
    if (lowerCategory === "approved") return "badge-approved";
    if (lowerCategory === "non-approved") return "badge-non-approved";
    return "";
  };

  return (
    <span className={`card-badge ${getBadgeVariant()}`} title={category}>
      {category}
    </span>
  );
};

export default Type;
