import React from 'react'
import styles from './Tag.module.css'

function Tag({tag, selected, toggleTagSelection, index}) {
  return (
    <div className={`${styles.tag} ${selected ? styles.selected : ''}`} onClick={()=>{toggleTagSelection(index)}}>
        {tag}
    </div>
  )
}

export default Tag