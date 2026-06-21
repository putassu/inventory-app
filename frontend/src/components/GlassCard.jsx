import React from 'react';
import './GlassCard.css';

const GlassCard = ({ children, className = '', hoverEffect = false, ...props }) => {
  return (
    <div 
      className={`glass-panel ${hoverEffect ? 'hoverable' : ''} ${className}`}
      {...props}
    >
      {children}
    </div>
  );
};

export default GlassCard;
