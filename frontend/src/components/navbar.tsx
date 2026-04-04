import React from 'react'

const Navbar = () => {
  return (
    <nav className='fixed h-15 w-screen px-10 bg-transparent z-100 text-zinc-300'>
<div className='flex h-full items-center justify-between'>
    <div className=''>Logo</div>
    <div className='flex flex-row gap-x-10' >
    <div className='cursor-pointer hover:scale-110 transition-all duration-250 ease-in-out hover:text-white'>Serivces</div>
    <div className='cursor-pointer hover:scale-110 transition-all duration-250 ease-in-out'>About us</div>
    <div className='cursor-pointer hover:scale-110 transition-all duration-250 ease-in-out'>Contact us</div>
    <div className='cursor-pointer hover:scale-110 transition-all duration-250 ease-in-out'>Pricing</div>
    </div>
</div>
    
    </nav>
  )
}

export default Navbar
