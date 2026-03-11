import React, { useState } from 'react';

const Owner = ({name}) => {
  const [showTooltip, setShowTooltip] = useState(false);

  // Extract initials from name
  const getInitials = (fullName) => {
    if (!fullName) return 'U';
    return fullName
      .split(' ')
      .map(word => word.charAt(0).toUpperCase())
      .slice(0, 2) // Take first 2 initials
      .join('');
  };

  return (
    <div className="card-owner">
      <div 
        className="owner-avatar"
        onMouseEnter={() => setShowTooltip(true)}
        onMouseLeave={() => setShowTooltip(false)}
      >
        {getInitials(name)}
        {showTooltip && (
          <div className="owner-tooltip">
            Created by {name}
          </div>
        )}
      </div>
    </div>
  )
};

export default Owner
